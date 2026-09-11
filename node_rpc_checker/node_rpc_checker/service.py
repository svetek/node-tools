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
from .scheduler import run_checks
from .spec import Spec


class Checker:
    def __init__(
        self,
        config: Config,
        client: Any,
        clock: Callable[[], float] = time.monotonic,
        *,
        trusted_client: Any = None,
    ):
        self.config, self.client, self.clock = config, client, clock
        self.spec = Spec(config.chain_id)
        self.adapter = adapter_for(config.chain_id)
        self.engine = Engine(self.spec, client, self.adapter, config.max_behind_blocks)
        reference_engine = (
            self.engine
            if trusted_client is None
            else Engine(self.spec, trusted_client, self.adapter, config.max_behind_blocks)
        )
        self.reference = TrustedReference(
            lambda: reference_engine.reference_height(config.trusted), config.trusted_ttl, clock
        )
        self.internal_errors: dict[tuple[str, str], int] = {}
        self.states: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in config.nodes}
        self.lock = threading.Lock()
        self.admissions: dict[tuple[str, str], dict[str, Any]] = {}
        self.progress: dict[tuple[str, str], tuple[int, float]] = {}
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
            if key.endswith("/height") and "node_height" in row:
                previous = self.progress.get((name, key))
                height = row["node_height"]
                if previous is not None and height < previous[0]:
                    row.update(ok=False, error="node height regressed", error_kind="rpc_error")
                progressed = (
                    self.clock() if previous is None or height > previous[0] else previous[1]
                )
                self.progress[name, key] = (height, progressed)
            self.states[name][key] = row
            self.update_admissions(name)
        return row

    def update_admissions(self, name: str) -> None:
        """Called under the state lock. Only complete strict checks grant admission."""
        now = self.clock()
        for mode in ("pruning", "archive"):
            levels = {"readyz", "pruning"} | ({"archive"} if mode == "archive" else set())
            rows = [
                (key, self.states[name].get(key, {}))
                for key, (level, _) in self.plans[name].items()
                if level in levels
            ]
            if any(
                row and not row.get("ok") and row.get("error_kind") != "reference_error"
                for _, row in rows
            ):
                self.admissions.pop((name, mode), None)
                continue
            strict = all(
                row.get("ok")
                and now - row["monotonic_at"]
                <= (self.config.ttl if row["mode"] == "readyz" else self.config.deep_ttl)
                and (
                    not key.endswith("/height")
                    or (self.reference.valid() and now < row.get("reference_expires_at", 0))
                )
                for key, row in rows
            )
            if strict:
                heights = {key: row["node_height"] for key, row in rows if key.endswith("/height")}
                if not heights:
                    continue
                expires = min(
                    row["reference_expires_at"] for key, row in rows if key.endswith("/height")
                )
                self.admissions[name, mode] = {
                    "expires": expires + self.config.reference_grace,
                    "heights": heights,
                }

    def compare(self, url: str) -> dict[str, Any]:
        start = self.clock()
        try:
            reference, reference_started = self.reference.snapshot()
        except RpcError:
            target_start = self.clock()
            # Always probe the target: a reference outage must not mask its failure.
            height = self.engine.height(url)
            return {
                "ok": False,
                "error": "trusted reference unavailable or stale",
                "error_kind": "reference_error",
                "node_height": height,
                "target_rpc_latency_ms": round((self.clock() - target_start) * 1000),
                "trusted_wait_ms": round((target_start - start) * 1000),
            }
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

    def run_mode(self, mode: str, stop: threading.Event) -> None:
        if mode not in ("readyz", "pruning", "archive"):
            raise ValueError("unknown check mode")
        workers = self.config.workers if mode == "readyz" else self.config.deep_workers
        interval = self.config.poll if mode == "readyz" else self.config.deep_interval
        # Interleave nodes before siblings, so one node cannot fill the queue.
        by_node = [
            [(name, key, fn) for key, (level, fn) in plan.items() if level == mode]
            for name, plan in self.plans.items()
        ]
        jobs = [
            row[i]
            for i in range(max(map(len, by_node), default=0))
            for row in by_node
            if i < len(row)
        ]
        while not stop.is_set():
            try:
                run_checks(
                    jobs, self.record, self.internal_error, workers, interval, stop, self.clock
                )
                return
            except Exception as exc:
                self.internal_error("service", mode, exc)
                stop.wait(interval)

    def snapshot(self, name: str | None = None) -> dict[str, dict[str, dict[str, Any]]]:
        with self.lock:
            states = copy.deepcopy(self.states if name is None else {name: self.states[name]})
            admissions = copy.deepcopy(self.admissions)
            progress = dict(self.progress)
        for node, checks in states.items():
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
                if key.endswith("/height"):
                    last = progress.get((node, key))
                    row["degraded_modes"] = [
                        mode
                        for mode in ("pruning", "archive")
                        if (admission := admissions.get((node, mode))) is not None
                        and self.config.reference_grace > 0
                        and not self.reference.valid()
                        and row.get("error_kind") == "reference_error"
                        and row["fresh"]
                        and self.clock() < admission["expires"]
                        and last is not None
                        and self.clock() - last[1] < self.config.progress_ttl
                        and row.get("node_height", -1) > admission["heights"].get(key, float("inf"))
                    ]
        return states

    def readiness(self, name, checks, mode):
        levels = {"readyz"}
        if mode in ("pruning", "archive"):
            levels.add("pruning")
        if mode == "archive":
            levels.add("archive")
        required = [k for k, (level, _) in self.plans[name].items() if level in levels]
        return all(
            checks.get(k, {}).get("fresh")
            and (checks[k].get("ok") or mode in checks[k].get("degraded_modes", []))
            for k in required
        )

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
                "degraded": not self.readiness(name, checks, "readyz")
                and any(self.readiness(name, checks, mode) for mode in ("pruning", "archive")),
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
        for key, value in self.reference.metrics().items():
            lines.append(f'node_rpc_checker_{key}{{chain="{self.config.chain_id}"}} {value}')

        def label(v):
            return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

        for name, checks in self.snapshot().items():
            for mode in ("readyz", "pruning", "archive"):
                degraded = (
                    mode != "readyz"
                    and self.readiness(name, checks, mode)
                    and not self.readiness(name, checks, "readyz")
                )
                lines.append(
                    f'node_rpc_checker_degraded{{chain="{self.config.chain_id}",node="{label(name)}",mode="{mode}"}} {int(degraded)}'
                )
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
            "degraded": "Whether this pool admits a previously verified growing node under bounded reference grace (1 or 0); lag is unverified.",
            "max_behind_blocks": "Inclusive permitted target lag behind the trusted height, in blocks.",
            "ready": "Whether all required checks for this node and mode are successful and fresh (1 or 0).",
            "check_ok": "Whether the last check succeeded; height checks also require a valid reference (1 or 0).",
            "check_fresh": "Whether the last check attempt is within its configured state TTL (1 or 0).",
            "last_attempt_timestamp": "Unix timestamp in seconds when the last check attempt completed.",
            "node_height": "Target HTTP block height from the last successful height comparison.",
            "trusted_height": "Trusted block height used by the last successful HTTP height comparison.",
            "delta_blocks": "Trusted minus target HTTP block height; negative means target ahead; last successful comparison.",
            "reference_valid": "Whether the shared trusted snapshot is successful and within its hard TTL (1 or 0).",
            "reference_refresh_attempts_total": "Actual trusted fetch attempts, both proactive and on-demand; excludes cache/backoff hits.",
            "reference_refresh_failures_total": "Trusted fetch attempts that failed or exceeded freshness TTL; excludes cache/backoff hits.",
            "reference_age_seconds": "Age since the start of the last successful trusted fetch; absent before first success.",
            "reference_refresh_duration_seconds": "Duration of the last completed trusted fetch, including retries; absent before first completion.",
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
            kind = "counter" if suffix.endswith("_total") else "gauge"
            output.extend(
                [
                    f"# HELP {metric} {descriptions[suffix]}",
                    f"# TYPE {metric} {kind}",
                    *samples,
                ]
            )
        return "\n".join(output) + "\n"


class BoundedHTTPServer(ThreadingHTTPServer):
    """Reject overload instead of allocating unbounded handler threads."""

    max_handlers = 32

    def __init__(self, *args, report_error=log_internal_error, **kwargs):
        self.slots = threading.BoundedSemaphore(self.max_handlers)
        self.report_error = report_error
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
        self.report_error(name, key, error)


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

    return BoundedHTTPServer(address, Handler, report_error=checker.internal_error)
