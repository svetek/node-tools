import copy
import json
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from . import __version__
from .adapters import adapter_for
from .config import Config
from .diagnostics import log_internal_error
from .engine import Engine
from .reference import TrustedReference
from .rpc import RpcError
from .spec import Spec


class Checker:
    def __init__(self, config: Config, client: Any, clock: Callable[[], float] = time.monotonic):
        self.config, self.client, self.clock = config, client, clock
        self.spec = Spec(config.chain_id)
        self.adapter = adapter_for(config.chain_id)
        self.engine = Engine(self.spec, client, self.adapter, config.max_behind_blocks)
        self.reference = TrustedReference(
            lambda: self.engine.reference_height(config.trusted), config.trusted_ttl, clock
        )
        self.internal_errors: dict[tuple[str, str], int] = {}
        self.states: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in config.nodes}
        self.lock = threading.Lock()
        self.plans = {}
        for name, node in config.nodes.items():
            if node.websocket_url and not self.adapter.websocket:
                raise ValueError("WebSocket is not defined for NEAR in these specs")
            rules = self.spec.rules(node.addons)
            plan: dict[str, tuple[str, Callable[[], dict[str, Any]]]] = {}
            for transport, url in [("http", node.rpc_url), ("ws", node.websocket_url)]:
                if not url:
                    continue
                for rule in rules:
                    plan[transport + "/" + rule.key] = (
                        rule.mode,
                        partial(self.engine.verify, url, rule),
                    )
                plan[transport + "/height"] = ("readyz", partial(self.compare, url))
            if node.websocket_url:
                subscribe, unsubscribe = self.adapter.subscription_requests(self.spec.directives)
                plan["ws/subscription"] = (
                    "readyz",
                    partial(client.subscription, node.websocket_url, subscribe, unsubscribe),
                )
            self.plans[name] = plan

    def internal_error(self, name: str, key: str, error: Exception) -> None:
        with self.lock:
            self.internal_errors[name, key] = self.internal_errors.get((name, key), 0) + 1
        log_internal_error(name, key, error)

    def record(self, name: str, key: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        start = self.clock()
        try:
            details = fn() or {}
            row = {"ok": True, **details}
        except RpcError as exc:
            row = {"ok": False, "error": str(exc), "error_kind": "rpc_error"}
        except Exception as exc:
            self.internal_error(name, key, exc)
            row = {"ok": False, "error": type(exc).__name__, "error_kind": "internal_error"}
        row.update(
            checked_at=time.time(),
            monotonic_at=start,
            mode=self.plans[name][key][0],
            latency_ms=round((self.clock() - start) * 1000),
        )
        with self.lock:
            self.states[name][key] = row
        return row

    def compare(self, url: str) -> dict[str, Any]:
        start = self.clock()
        reference, reference_started = self.reference.snapshot()
        target_start = self.clock()
        result: dict[str, Any] = self.engine.compare_height(url, reference)
        result.update(
            trusted_wait_ms=round((target_start - start) * 1000),
            target_rpc_latency_ms=round((self.clock() - target_start) * 1000),
            reference_expires_at=reference_started + self.config.trusted_ttl,
        )
        if not self.reference.valid() or self.clock() >= result["reference_expires_at"]:
            raise RpcError("trusted reference unavailable or stale")
        return result

    def cycle(self, name, *, mode=None, pool=None, stop=None):
        """Run selected checks once. Scheduling belongs exclusively to run_mode."""
        jobs = []
        for key, (level, fn) in self.plans[name].items():
            if mode is not None and level != mode:
                continue
            jobs.append((key, fn))

        # Independent core checks should not expire while slow siblings run.
        # Each target is read after obtaining a bounded-age trusted snapshot.
        def record_unless_stopping(key, fn):
            if stop is None or not stop.is_set():
                self.record(name, key, fn)

        def execute(executor):
            futures = [executor.submit(record_unless_stopping, key, fn) for key, fn in jobs]
            for future in futures:
                future.result()

        if pool is None:
            with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
                execute(executor)
        else:
            execute(pool)

    def run(self, name: str, stop: threading.Event) -> None:
        self.run_mode(name, "readyz", self.config.poll, stop)

    def run_reference(self, stop: threading.Event) -> None:
        # A single proactive updater for all nodes and transports. Never extend
        # the hard TTL of the previous snapshot while a refresh is in flight.
        while not stop.is_set():
            try:
                self.reference.get(refresh=True)
            except RpcError:
                pass  # Reference failure already invalidates readiness.
            except Exception as exc:
                self.internal_error("service", "trusted_refresh", exc)
            stop.wait(self.config.trusted_refresh_interval)

    def run_mode(self, name: str, mode: str, interval: float, stop: threading.Event) -> None:
        workers = self.config.workers if mode == "readyz" else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while not stop.is_set():
                try:
                    self.cycle(name, pool=pool, mode=mode, stop=stop)
                except Exception as exc:
                    self.internal_error(name, mode, exc)
                stop.wait(interval)

    def run_deep(self, name: str, archive: bool, stop: threading.Event) -> None:
        # Archive I/O must never delay the regular height/shard polling loop.
        self.run_mode(name, "archive" if archive else "pruning", self.config.deep_interval, stop)

    def snapshot(self, name: str | None = None) -> dict[str, dict[str, dict[str, Any]]]:
        with self.lock:
            states = copy.deepcopy(self.states if name is None else {name: self.states[name]})
        for checks in states.values():
            for key, row in checks.items():
                age = max(0, self.clock() - row.pop("monotonic_at"))
                reference_expires_at = row.pop("reference_expires_at", float("inf"))
                row["age_seconds"] = round(age, 3)
                row["fresh"] = age <= (
                    self.config.deep_ttl if row["mode"] != "readyz" else self.config.ttl
                )
                if (
                    row["ok"]
                    and key.endswith("/height")
                    and (not self.reference.valid() or self.clock() >= reference_expires_at)
                ):
                    row.update(
                        ok=False,
                        error="trusted reference unavailable or stale",
                        error_kind="reference_error",
                    )
        return states

    def readiness(self, name, checks, mode):
        levels = {"readyz"}
        if mode in ("pruning", "archive"):
            levels.add("pruning")
        if mode == "archive":
            levels.add("archive")
        required = [k for k, (level, _) in self.plans[name].items() if level in levels]
        return all(checks.get(k, {}).get("ok") and checks[k].get("fresh") for k in required)

    def response(self, path: str) -> tuple[int, dict[str, Any]]:
        parts = urlsplit(path).path.strip("/").split("/")
        endpoint = parts[0]
        if endpoint == "healthz" and len(parts) == 1:
            return 200, {"alive": True, "version": __version__}
        if endpoint not in ("readyz", "pruning", "archive", "status") or len(parts) > 2:
            return 404, {"error": "not found"}
        if len(parts) == 2:
            if parts[1] not in self.states:
                return 404, {"error": "unknown node"}
        states = self.snapshot(parts[1] if len(parts) == 2 else None)
        rows = {
            name: {
                "ready": self.readiness(name, checks, endpoint),
                "readiness": {
                    m: self.readiness(name, checks, m) for m in ("readyz", "pruning", "archive")
                },
                "checks": checks,
            }
            for name, checks in states.items()
        }
        ready = all(row["ready"] for row in rows.values())
        return (200 if endpoint == "status" or ready else 503), {
            "chain_id": self.config.chain_id,
            "max_behind_blocks": self.config.max_behind_blocks,
            "version": __version__,
            "ready": ready,
            "mode": endpoint,
            "spec_sha256": self.spec.hashes,
            "nodes": rows,
        }

    def metrics(self) -> str:
        lines = [
            f'node_rpc_checker_max_behind_blocks{{chain="{self.config.chain_id}"}} {self.config.max_behind_blocks}'
        ]

        def label(v):
            return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

        for name, checks in self.snapshot().items():
            for mode in ("readyz", "pruning", "archive"):
                lines.append(
                    f'node_rpc_checker_ready{{chain="{self.config.chain_id}",node="{label(name)}",mode="{mode}"}} {int(self.readiness(name, checks, mode))}'
                )
            for key, row in checks.items():
                tags = f'chain="{self.config.chain_id}",node="{label(name)}",check="{label(key)}"'
                lines.append(f"node_rpc_checker_check_ok{{{tags}}} {int(row['ok'])}")
                lines.append(f"node_rpc_checker_check_fresh{{{tags}}} {int(row['fresh'])}")
                lines.append(f"node_rpc_checker_latency_ms{{{tags}}} {row['latency_ms']}")
                for metric in ("target_rpc_latency_ms", "trusted_wait_ms"):
                    if metric in row:
                        lines.append(f"node_rpc_checker_{metric}{{{tags}}} {row[metric]}")
                lines.append(
                    f"node_rpc_checker_last_attempt_timestamp{{{tags}}} {row['checked_at']}"
                )
            for key in ("node_height", "trusted_height", "delta_blocks"):
                if key in checks.get("http/height", {}):
                    lines.append(
                        f'node_rpc_checker_{key}{{chain="{self.config.chain_id}",node="{label(name)}"}} {checks["http/height"][key]}'
                    )
        with self.lock:
            errors = dict(self.internal_errors)
        for (name, key), count in errors.items():
            lines.append(
                f'node_rpc_checker_internal_errors_total{{chain="{self.config.chain_id}",node="{label(name)}",check="{label(key)}"}} {count}'
            )
        descriptions = {
            "latency_ms": "Whole check duration including reference work (legacy name).",
            "target_rpc_latency_ms": "Target height RPC duration excluding reference work; successful checks only.",
            "trusted_wait_ms": "Reference acquisition duration including refresh or lock wait; successful height checks only.",
            "internal_errors_total": "Internal errors by configured node/check or fixed service operation.",
        }
        # Group families, with metadata preceding every family's samples.
        families: dict[str, list[str]] = {}
        for line in lines:
            metric = line.split("{", 1)[0]
            families.setdefault(metric, []).append(line)
        output = []
        for metric, samples in families.items():
            suffix = metric.removeprefix("node_rpc_checker_")
            kind = "counter" if suffix == "internal_errors_total" else "gauge"
            output.extend(
                [
                    f"# HELP {metric} {descriptions.get(suffix, suffix.replace('_', ' ') + '.')}",
                    f"# TYPE {metric} {kind}",
                    *samples,
                ]
            )
        return "\n".join(output) + "\n"


class BoundedHTTPServer(ThreadingHTTPServer):
    """Reject overload instead of allocating unbounded handler threads."""

    max_handlers = 32

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(self.max_handlers)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(5)
        return request, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, Exception):
            self.internal_error("monitoring", "http_handler", error)

    def internal_error(self, name: str, key: str, error: Exception) -> None:
        log_internal_error(name, key, error)


def make_server(checker, address):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if urlsplit(self.path).path == "/metrics":
                    code, body, content_type = (
                        200,
                        checker.metrics().encode(),
                        "text/plain; version=0.0.4",
                    )
                else:
                    code, data = checker.response(self.path)
                    body, content_type = json.dumps(data).encode(), "application/json"
            except Exception as error:
                checker.internal_error("monitoring", "response", error)
                code, body, content_type = (
                    500,
                    b'{"error":"internal server error"}',
                    "application/json",
                )
            try:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                # Headers may already be sent: never attempt a second response.
                self.close_connection = True

        def log_message(self, *_args):
            pass

    class CheckerHTTPServer(BoundedHTTPServer):
        def internal_error(self, name: str, key: str, error: Exception) -> None:
            checker.internal_error(name, key, error)

    return CheckerHTTPServer(address, Handler)
