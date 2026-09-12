import copy
import json
import logging
import math
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
from .rpc import NodeBehind, ReferenceUnavailable, RpcEndpointError, RpcError
from .scheduler import run_checks
from .spec import Spec

METRIC_DESCRIPTIONS = {
    "node_endpoints_info": "Configured backend origins without path, query or userinfo; one sample per node, including unavailable nodes.",
    "node_type_info": "Detected backend storage type from fresh successful HTTP deep checks; type is prune or archive, and the sample is absent when neither check passes.",
    "rpc_endpoint_info": "Configured RPC origin by node, role and transport, without path, query or userinfo.",
    "check_consecutive_failures": "Consecutive failed completed attempts of this check; success including unverified target height resets to zero.",
    "check_last_success_timestamp_seconds": "Unix time of last successful completed target check; zero before any success; retained across failures.",
    "rpc_last_error_timestamp_seconds": "Unix time of the last exhausted target transport/response failure or failed trusted refresh; zero before any failure, retained across recovery.",
    "reference_cache_fresh": "Whether the last successful trusted observation is within its TTL, independent of the latest refresh outcome (1 or 0).",
    "height_comparison_verified": "Whether the latest target height comparison passed with a still-fresh trusted observation and fresh local result (1 or 0).",
    "check_duration_seconds": "Duration of the last completed check including reference acquisition, in seconds (millisecond resolution).",
    "target_rpc_duration_seconds": "Duration of the target height request excluding reference acquisition, in seconds (millisecond resolution).",
    "reference_wait_duration_seconds": "Reference acquisition duration for the last height probe, in seconds (millisecond resolution).",
    "check_last_completed_timestamp_seconds": "Unix time in seconds when the last check attempt completed, regardless of outcome.",
    "check_results_total": "Completed check attempts by outcome and bounded error kind; does not count status reads or subsequent TTL expiry.",
    "reference_up": "Whether the latest trusted refresh succeeded and its observation is fresh (1 or 0).",
    "rpc_up": "Whether the latest endpoint height probe succeeded and is fresh (1 or 0); independent of lag validation.",
    "degraded": "Whether this mode is available without a fresh trusted height comparison (1 or 0); lag is unverified.",
    "max_behind_blocks": "Inclusive permitted target lag behind the trusted height, in blocks.",
    "ready": "Whether all required checks for this node and mode are successful and fresh (1 or 0).",
    "check_ok": "Whether the target check succeeded; unavailable trusted alone does not fail a check (1 or 0).",
    "check_fresh": "Whether the last check attempt is within its configured state TTL (1 or 0).",
    "node_height": "Target HTTP block height from the last successful height comparison.",
    "trusted_height": "Trusted height used for the latest HTTP height diagnostic; may be the last known stale observation.",
    "delta_blocks": "Known trusted minus current target HTTP height; may use a stale reference; absent if trusted is unknown.",
    "reference_refresh_attempts_total": "Actual trusted fetch attempts, both proactive and on-demand; excludes cache/backoff hits.",
    "reference_refresh_failures_total": "Trusted fetch attempts that failed or exceeded freshness TTL; excludes cache/backoff hits.",
    "reference_age_seconds": "Age since the start of the last successful trusted fetch; absent before first success.",
    "reference_refresh_duration_seconds": "Duration of the last completed trusted fetch, including retries; absent before first completion.",
    "internal_errors_total": "Internal errors by configured node/check or fixed service operation.",
}


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
        self.check_results: dict[tuple[str, str, str, str], int] = {}
        self.check_history: dict[tuple[str, str], tuple[int, float]] = {}
        self.rpc_last_errors: dict[tuple[str, str], float] = {}
        self.states: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in config.nodes}
        self.lock = threading.Lock()
        self.progress: dict[tuple[str, str], tuple[int, float]] = {}
        self.missing_metric_help: set[str] = set()
        self.plans = {}
        for name, node in config.nodes.items():
            if node.websocket_url and not self.adapter.websocket:
                raise ValueError("WebSocket is not defined for NEAR in these specs")
            rules = self.spec.rules(node.addons)
            if node.node_type == "prune":
                rules = [rule for rule in rules if rule.mode != "archive"]
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
        self.warn_capacity()

    def capacity_estimates(self) -> list[dict[str, Any]]:
        """One-timeout-per-task heuristic, not a bound on actual RPC work."""
        estimates = []
        for mode in ("readyz", "pruning", "archive"):
            jobs = sum(level == mode for plan in self.plans.values() for level, _ in plan.values())
            workers = self.config.workers if mode == "readyz" else self.config.deep_workers
            interval = self.config.poll if mode == "readyz" else self.config.deep_interval
            ttl = self.config.ttl if mode == "readyz" else self.config.deep_ttl
            nominal_round = math.ceil(jobs / workers) * self.config.timeout
            estimates.append(
                dict(
                    mode=mode,
                    jobs=jobs,
                    workers=workers,
                    interval=interval,
                    ttl=ttl,
                    nominal_round=nominal_round,
                    at_risk=jobs > 0 and nominal_round + interval >= ttl,
                )
            )
        return estimates

    def warn_capacity(self) -> None:
        for estimate in self.capacity_estimates():
            if estimate["at_risk"]:
                logging.warning(
                    "Check pool capacity risk: mode=%s jobs=%s workers=%s "
                    "nominal_round_seconds=%g interval_seconds=%g ttl_seconds=%g; "
                    "one target timeout per task, not a throughput guarantee; "
                    "retries, multi-call tasks and trusted waits may increase duration. "
                    "Review workers, TTLs or fleet size; readiness may become stale.",
                    estimate["mode"],
                    estimate["jobs"],
                    estimate["workers"],
                    estimate["nominal_round"],
                    estimate["interval"],
                    estimate["ttl"],
                )

    def metric_help(self, suffix: str) -> str:
        description = METRIC_DESCRIPTIONS.get(suffix)
        if description is not None:
            return description
        with self.lock:
            report = suffix not in self.missing_metric_help
            self.missing_metric_help.add(suffix)
        if report:
            self.internal_error("monitoring", "metric_help", KeyError("missing metric description"))
        return "Metric description unavailable; consult the checker documentation."

    def internal_error(self, name: str, key: str, error: Exception) -> None:
        with self.lock:
            self.internal_errors[name, key] = self.internal_errors.get((name, key), 0) + 1
        log_internal_error(name, key, error)

    def record(self, name: str, key: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        start = self.clock()
        endpoint_failed = False
        try:
            details = fn() or {}
            if {"ok", "error", "error_kind"}.intersection(details):
                raise ValueError("check details contain reserved outcome keys")
            row = {"ok": True, **details}
        except ReferenceUnavailable as exc:
            row = {
                "ok": True,
                "reference_fresh": False,
                "reference_error": str(exc),
                "node_height": exc.node_height,
                "target_rpc_latency_ms": exc.target_rpc_latency_ms,
                "trusted_wait_ms": exc.trusted_wait_ms,
            }
            height, observed = self.reference.last_success()
            if height is not None:
                row.update(trusted_height=height, delta_blocks=height - exc.node_height)
            if observed is not None:
                row["reference_expires_at"] = observed + self.config.trusted_ttl
        except NodeBehind as exc:
            row = {
                **exc.details,
                "ok": False,
                "error": str(exc),
                "error_kind": "rpc_error",
                "reference_fresh": True,
            }
        except RpcEndpointError as exc:
            endpoint_failed = True
            row = {"ok": False, "error": str(exc), "error_kind": "rpc_error"}
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
            failures, last_success = self.check_history.get((name, key), (0, 0.0))
            self.check_history[name, key] = (
                (0, row["checked_at"]) if row["ok"] else (failures + 1, last_success)
            )
            if endpoint_failed:
                endpoint_key = (name, key.split("/", 1)[0])
                self.rpc_last_errors[endpoint_key] = max(
                    self.rpc_last_errors.get(endpoint_key, 0.0), row["checked_at"]
                )
            if not row["ok"]:
                outcome = "failure"
                error_kind = row.get("error_kind", "internal_error")
                if error_kind not in ("rpc_error", "internal_error"):
                    error_kind = "internal_error"
            elif key.endswith("/height") and not row.get("reference_fresh", False):
                outcome, error_kind = "unverified", "reference_error"
            else:
                outcome, error_kind = "success", "none"
            counter_key = (name, key, outcome, error_kind)
            self.check_results[counter_key] = self.check_results.get(counter_key, 0) + 1
        return row

    def compare(self, url: str) -> dict[str, Any]:
        start = self.clock()
        try:
            # After bootstrap, the independent updater owns retries. Target checks
            # must not queue behind an unavailable reference's network requests.
            if self.reference.has_attempted_refresh() and not self.reference.available():
                raise RpcError("trusted reference unavailable or stale")
            reference, reference_started = self.reference.snapshot()
        except RpcError:
            target_start = self.clock()
            # Always probe the target: a reference outage must not mask its failure.
            height = self.engine.height(url)
            raise ReferenceUnavailable(
                height,
                round((self.clock() - target_start) * 1000),
                round((target_start - start) * 1000),
            ) from None
        target_start = self.clock()
        try:
            result: dict[str, Any] = self.engine.compare_height(url, reference)
        except NodeBehind as exc:
            if (
                self.reference.available()
                and self.clock() < reference_started + self.config.trusted_ttl
            ):
                raise
            raise ReferenceUnavailable(
                exc.details["node_height"],
                round((self.clock() - target_start) * 1000),
                round((target_start - start) * 1000),
            ) from None
        result.update(
            reference_fresh=True,
            trusted_wait_ms=round((target_start - start) * 1000),
            target_rpc_latency_ms=round((self.clock() - target_start) * 1000),
            reference_expires_at=reference_started + self.config.trusted_ttl,
        )
        if not self.reference.available() or self.clock() >= result["reference_expires_at"]:
            raise ReferenceUnavailable(
                result["node_height"],
                result["target_rpc_latency_ms"],
                result["trusted_wait_ms"],
            )
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
                    and (not self.reference.available() or self.clock() >= reference_expires_at)
                ):
                    row.update(
                        reference_fresh=False,
                        reference_error="trusted reference unavailable or stale",
                    )
                if key.endswith("/height"):
                    last = progress.get((node, key))
                    if (
                        row["ok"]
                        and not row.get("reference_fresh", False)
                        and (last is None or self.clock() - last[1] >= self.config.progress_ttl)
                    ):
                        row.update(
                            ok=False, error="node height is not progressing", error_kind="rpc_error"
                        )
        return states

    def readiness(self, name, checks, mode):
        if mode == "archive" and self.config.nodes[name].node_type == "prune":
            return False
        levels = {"readyz"}
        if mode in ("pruning", "archive"):
            levels.add("pruning")
        if mode == "archive":
            levels.add("archive")
        required = [k for k, (level, _) in self.plans[name].items() if level in levels]
        return all(checks.get(k, {}).get("fresh") and checks[k].get("ok") for k in required)

    def node_type(self, name: str, checks: dict[str, dict[str, Any]]) -> str | None:
        """Return the storage type proven by fresh successful HTTP deep checks."""
        checks_by_mode = {
            mode: [
                key
                for key, (level, _) in self.plans[name].items()
                if level == mode and key.startswith("http/")
            ]
            for mode in ("archive", "pruning")
        }

        def passed(mode: str) -> bool:
            required = checks_by_mode[mode]
            return bool(required) and all(
                checks.get(key, {}).get("ok") and checks[key].get("fresh") for key in required
            )

        if passed("archive"):
            return "archive"
        if passed("pruning"):
            return "prune"
        return None

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
                "degraded": any(
                    k.endswith("/height") and not r.get("reference_fresh", False)
                    for k, r in checks.items()
                ),
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
            "reference": self.reference.metrics(),
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

        def origin(url):
            parsed = urlsplit(url)
            if not parsed.hostname:
                return ""
            host = parsed.hostname
            if ":" in host:
                host = "[" + host + "]"
            port = ":" + str(parsed.port) if parsed.port is not None else ""
            return parsed.scheme + "://" + host + port

        with self.lock:
            history = dict(self.check_history)
            rpc_errors = dict(self.rpc_last_errors)

        def rpc_sample(name, role, transport, url, up):
            tags = f'chain="{self.config.chain_id}",node="{label(name)}",role="{role}",transport="{transport}"'
            lines.append(
                f'node_rpc_checker_rpc_endpoint_info{{{tags},address="{label(origin(url))}"}} 1'
            )
            last_error = (
                self.reference.last_error_timestamp()
                if role == "trusted"
                else rpc_errors.get((name, transport), 0.0)
            )
            lines.append(
                f"node_rpc_checker_rpc_last_error_timestamp_seconds{{{tags}}} {last_error}"
            )
            lines.append(f"node_rpc_checker_rpc_up{{{tags}}} {up}")

        rpc_sample("", "trusted", "http", self.config.trusted, int(self.reference.available()))
        for name, checks in self.snapshot().items():
            node = self.config.nodes[name]
            lines.append(
                f'node_rpc_checker_node_endpoints_info{{chain="{self.config.chain_id}",node="{label(name)}",http="{label(origin(node.rpc_url))}",websocket="{label(origin(node.websocket_url))}"}} 1'
            )
            detected_type = self.node_type(name, checks)
            if detected_type is not None:
                lines.append(
                    f'node_rpc_checker_node_type_info{{chain="{self.config.chain_id}",node="{label(name)}",type="{detected_type}"}} 1'
                )
            for key, (mode, _) in self.plans[name].items():
                failures, last_success = history.get((name, key), (0, 0.0))
                tags = f'chain="{self.config.chain_id}",node="{label(name)}",check="{label(key)}",mode="{mode}"'
                lines.append(f"node_rpc_checker_check_consecutive_failures{{{tags}}} {failures}")
                lines.append(
                    f"node_rpc_checker_check_last_success_timestamp_seconds{{{tags}}} {last_success}"
                )
            for transport, url in (("http", node.rpc_url), ("ws", node.websocket_url)):
                if url:
                    height = checks.get(transport + "/height", {})
                    up = int(bool(height.get("fresh") and "node_height" in height))
                    rpc_sample(name, "backend", transport, url, up)
                    verified = int(
                        bool(
                            height.get("ok")
                            and height.get("fresh")
                            and height.get("reference_fresh")
                        )
                    )
                    lines.append(
                        f'node_rpc_checker_height_comparison_verified{{chain="{self.config.chain_id}",node="{label(name)}",transport="{transport}"}} {verified}'
                    )
            for mode in ("readyz", "pruning", "archive"):
                degraded = self.readiness(name, checks, mode) and any(
                    k.endswith("/height") and not r.get("reference_fresh", False)
                    for k, r in checks.items()
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
                lines.append(
                    f"node_rpc_checker_check_duration_seconds{{{tags}}} {row['latency_ms'] / 1000}"
                )
                for metric in ("target_rpc_latency_ms", "trusted_wait_ms"):
                    if metric in row:
                        canonical = (
                            "target_rpc_duration_seconds"
                            if metric == "target_rpc_latency_ms"
                            else "reference_wait_duration_seconds"
                        )
                        lines.append(f"node_rpc_checker_{canonical}{{{tags}}} {row[metric] / 1000}")
                lines.append(
                    f"node_rpc_checker_check_last_completed_timestamp_seconds{{{tags}}} {row['checked_at']}"
                )
            for key in ("node_height", "trusted_height", "delta_blocks"):
                if key in checks.get("http/height", {}):
                    lines.append(
                        f'node_rpc_checker_{key}{{chain="{self.config.chain_id}",node="{label(name)}"}} {checks["http/height"][key]}'
                    )
        with self.lock:
            errors = dict(self.internal_errors)
            results = dict(self.check_results)
        for (name, key, outcome, error_kind), count in results.items():
            tags = f'chain="{self.config.chain_id}",node="{label(name)}",check="{label(key)}",outcome="{outcome}",error_kind="{error_kind}"'
            lines.append(f"node_rpc_checker_check_results_total{{{tags}}} {count}")
        for (name, key), count in errors.items():
            lines.append(
                f'node_rpc_checker_internal_errors_total{{chain="{self.config.chain_id}",node="{label(name)}",check="{label(key)}"}} {count}'
            )
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
                    f"# HELP {metric} {self.metric_help(suffix)}",
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
