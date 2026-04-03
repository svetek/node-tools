from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .config import Config
from .rpc import RpcClient, RpcError

LOGGER = logging.getLogger("evm_height_checker")


def utc_timestamp() -> float:
    return time.time()


@dataclass(frozen=True)
class CheckResult:
    local_height: int
    remote_height: int
    delta_blocks: int
    max_behind_blocks: int
    healthy: bool
    summary: str


class RpcEndpointError(RuntimeError):
    def __init__(self, url: str, cause: Exception) -> None:
        self.url = url
        self.cause = cause
        super().__init__(f"rpc failed for {url}: {cause}")


@dataclass
class EndpointState:
    url: str
    up: bool = False
    last_success_at: float | None = None
    last_error: str | None = None
    last_error_at: float | None = None


def evaluate_heights(local_height: int, remote_height: int, max_behind_blocks: int) -> CheckResult:
    delta_blocks = remote_height - local_height
    healthy = delta_blocks <= max_behind_blocks
    summary = (
        "local node is within the allowed lag"
        if healthy
        else "local node is behind the remote node beyond the allowed lag"
    )
    return CheckResult(
        local_height=local_height,
        remote_height=remote_height,
        delta_blocks=delta_blocks,
        max_behind_blocks=max_behind_blocks,
        healthy=healthy,
        summary=summary,
    )


@dataclass
class SharedState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    started_at: float = field(default_factory=utc_timestamp)
    last_attempt_at: float | None = None
    last_success_at: float | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    result: CheckResult | None = None
    local_rpc: EndpointState | None = None
    remote_rpc: EndpointState | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "started_at": self.started_at,
                "last_attempt_at": self.last_attempt_at,
                "last_success_at": self.last_success_at,
                "last_error": self.last_error,
                "consecutive_failures": self.consecutive_failures,
                "result": asdict(self.result) if self.result else None,
                "local_rpc": asdict(self.local_rpc) if self.local_rpc else None,
                "remote_rpc": asdict(self.remote_rpc) if self.remote_rpc else None,
            }

    def set_endpoint_urls(self, local_url: str, remote_url: str) -> None:
        with self.lock:
            if self.local_rpc is None:
                self.local_rpc = EndpointState(url=local_url)
            else:
                self.local_rpc.url = local_url
            if self.remote_rpc is None:
                self.remote_rpc = EndpointState(url=remote_url)
            else:
                self.remote_rpc.url = remote_url

    def update_success(self, result: CheckResult, now: float) -> None:
        with self.lock:
            self.last_attempt_at = now
            self.last_success_at = now
            self.last_error = None
            self.consecutive_failures = 0
            self.result = result

    def update_failure(self, error: str, now: float) -> None:
        with self.lock:
            self.last_attempt_at = now
            self.last_error = error
            self.consecutive_failures += 1

    def update_endpoint_success(self, url: str, now: float) -> None:
        with self.lock:
            endpoint = self._endpoint_by_url(url)
            endpoint.up = True
            endpoint.last_success_at = now
            endpoint.last_error = None
            endpoint.last_error_at = None

    def update_endpoint_failure(self, url: str, error: str, now: float) -> None:
        with self.lock:
            endpoint = self._endpoint_by_url(url)
            endpoint.up = False
            endpoint.last_error = error
            endpoint.last_error_at = now

    def _endpoint_by_url(self, url: str) -> EndpointState:
        if self.local_rpc and self.local_rpc.url == url:
            return self.local_rpc
        if self.remote_rpc and self.remote_rpc.url == url:
            return self.remote_rpc
        raise ValueError(f"unknown endpoint url: {url}")

    def is_ready(self, now: float, state_ttl_seconds: float) -> bool:
        with self.lock:
            if self.result is None or self.last_success_at is None:
                return False
            if now - self.last_success_at > state_ttl_seconds:
                return False
            return self.result.healthy


class CheckerService:
    def __init__(
        self,
        config: Config,
        state: SharedState,
        rpc_client: RpcClient,
        time_fn: Callable[[], float] = utc_timestamp,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.state = state
        self.rpc_client = rpc_client
        self.time_fn = time_fn
        self.sleep_fn = sleep_fn
        self.state.set_endpoint_urls(config.local_rpc_url, config.remote_rpc_url)

    def run_once(self) -> CheckResult:
        now = self.time_fn()
        try:
            local_height, remote_height = self._fetch_pair()
            result = evaluate_heights(
                local_height=local_height,
                remote_height=remote_height,
                max_behind_blocks=self.config.max_behind_blocks,
            )
            self.state.update_success(result, now)
            LOGGER.info(
                "block heights checked",
                extra={
                    "local_height": result.local_height,
                    "remote_height": result.remote_height,
                    "delta_blocks": result.delta_blocks,
                    "healthy": result.healthy,
                    "consecutive_failures": self.state.snapshot()["consecutive_failures"],
                },
            )
            return result
        except Exception as exc:
            self.state.update_failure(str(exc), now)
            extra = {
                "consecutive_failures": self.state.snapshot()["consecutive_failures"],
            }
            if isinstance(exc, RpcEndpointError):
                extra.update({"url": exc.url})
                LOGGER.error(f"failed to check block heights: {exc}", extra=extra)
            elif isinstance(exc, RpcError):
                LOGGER.error(f"failed to check block heights: {exc}", extra=extra)
            else:
                LOGGER.exception("failed to check block heights", extra=extra)
            raise

    def run_forever(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            cycle_started_at = self.time_fn()
            try:
                self.run_once()
            except Exception:
                pass

            elapsed = self.time_fn() - cycle_started_at
            sleep_seconds = max(self.config.poll_interval_seconds - elapsed, 0.0)
            stop_event.wait(timeout=sleep_seconds)

    def _fetch_pair(self) -> tuple[int, int]:
        with ThreadPoolExecutor(max_workers=2) as executor:
            local_future = executor.submit(
                self._fetch_with_retries, self.config.local_rpc_url
            )
            remote_future = executor.submit(
                self._fetch_with_retries, self.config.remote_rpc_url
            )
            local_result = self._resolve_future(local_future, self.config.local_rpc_url)
            remote_result = self._resolve_future(remote_future, self.config.remote_rpc_url)

            errors = [error for error in (local_result[1], remote_result[1]) if error is not None]
            if errors:
                raise errors[0]

            return local_result[0], remote_result[0]

    def _resolve_future(
        self,
        future: Any,
        url: str,
    ) -> tuple[int | None, Exception | None]:
        now = self.time_fn()
        try:
            value = future.result()
            self.state.update_endpoint_success(url, now)
            return value, None
        except Exception as exc:
            self.state.update_endpoint_failure(url, str(exc), now)
            return None, exc

    def _fetch_with_retries(self, url: str) -> int:
        last_error: Exception | None = None
        attempts = self.config.rpc_retry_count + 1
        for attempt in range(1, attempts + 1):
            try:
                return self.rpc_client.get_block_number(url)
            except Exception as exc:
                last_error = exc
                if attempt == attempts:
                    break
                self.sleep_fn(self.config.retry_delay_seconds)
        assert last_error is not None
        raise RpcEndpointError(url=url, cause=last_error)


class StatusHandler(BaseHTTPRequestHandler):
    server_version = "evm-height-checker/0.1"

    def do_GET(self) -> None:  # noqa: N802
        now = time.time()
        server: "MonitoringHTTPServer" = self.server  # type: ignore[assignment]

        if self.path == "/healthz":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return

        if self.path == "/readyz":
            snapshot = server.state.snapshot()
            ready = server.state.is_ready(now, server.config.state_ttl_seconds)
            payload = {
                "status": "ready" if ready else "not_ready",
                "ready": ready,
                **snapshot,
            }
            self._write_json(HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE, payload)
            return

        if self.path == "/status":
            snapshot = server.state.snapshot()
            snapshot["ready"] = server.state.is_ready(now, server.config.state_ttl_seconds)
            self._write_json(HTTPStatus.OK, snapshot)
            return

        if self.path == "/metrics":
            metrics = render_metrics(server.state.snapshot(), server.config, now)
            self._write_text(HTTPStatus.OK, metrics, content_type="text/plain; version=0.0.4")
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info(
            "http request",
            extra={"endpoint": self.path},
        )

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_text(self, status: HTTPStatus, payload: str, content_type: str) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MonitoringHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], config: Config, state: SharedState) -> None:
        super().__init__(server_address, StatusHandler)
        self.config = config
        self.state = state


def render_metrics(snapshot: dict[str, Any], config: Config, now: float) -> str:
    result = snapshot["result"] or {}
    local_rpc = snapshot["local_rpc"] or {}
    remote_rpc = snapshot["remote_rpc"] or {}
    ready = False
    if snapshot["last_success_at"] is not None and result:
        ready = (
            now - snapshot["last_success_at"] <= config.state_ttl_seconds
            and result.get("healthy", False)
        )

    local_height = result.get("local_height", 0)
    remote_height = result.get("remote_height", 0)
    delta_blocks = result.get("delta_blocks", 0)
    healthy = 1 if result.get("healthy", False) else 0
    last_success_at = snapshot["last_success_at"] or 0
    last_attempt_at = snapshot["last_attempt_at"] or 0
    local_rpc_up = 1 if local_rpc.get("up", False) else 0
    remote_rpc_up = 1 if remote_rpc.get("up", False) else 0
    local_rpc_last_success_at = local_rpc.get("last_success_at") or 0
    remote_rpc_last_success_at = remote_rpc.get("last_success_at") or 0
    local_rpc_last_error_at = local_rpc.get("last_error_at") or 0
    remote_rpc_last_error_at = remote_rpc.get("last_error_at") or 0

    lines = [
        "# HELP evm_height_checker_local_height Latest local node block height.",
        "# TYPE evm_height_checker_local_height gauge",
        f"evm_height_checker_local_height {local_height}",
        "# HELP evm_height_checker_remote_height Latest remote node block height.",
        "# TYPE evm_height_checker_remote_height gauge",
        f"evm_height_checker_remote_height {remote_height}",
        "# HELP evm_height_checker_local_rpc_up Local RPC endpoint availability from the last check.",
        "# TYPE evm_height_checker_local_rpc_up gauge",
        f"evm_height_checker_local_rpc_up {local_rpc_up}",
        "# HELP evm_height_checker_remote_rpc_up Remote RPC endpoint availability from the last check.",
        "# TYPE evm_height_checker_remote_rpc_up gauge",
        f"evm_height_checker_remote_rpc_up {remote_rpc_up}",
        "# HELP evm_height_checker_delta_blocks Remote height minus local height.",
        "# TYPE evm_height_checker_delta_blocks gauge",
        f"evm_height_checker_delta_blocks {delta_blocks}",
        "# HELP evm_height_checker_healthy Last successful comparison status.",
        "# TYPE evm_height_checker_healthy gauge",
        f"evm_height_checker_healthy {healthy}",
        "# HELP evm_height_checker_ready Current readiness status with TTL applied.",
        "# TYPE evm_height_checker_ready gauge",
        f"evm_height_checker_ready {1 if ready else 0}",
        "# HELP evm_height_checker_consecutive_failures Consecutive failed checks.",
        "# TYPE evm_height_checker_consecutive_failures gauge",
        f"evm_height_checker_consecutive_failures {snapshot['consecutive_failures']}",
        "# HELP evm_height_checker_last_success_timestamp Unix timestamp of the last successful check.",
        "# TYPE evm_height_checker_last_success_timestamp gauge",
        f"evm_height_checker_last_success_timestamp {last_success_at}",
        "# HELP evm_height_checker_last_attempt_timestamp Unix timestamp of the last attempted check.",
        "# TYPE evm_height_checker_last_attempt_timestamp gauge",
        f"evm_height_checker_last_attempt_timestamp {last_attempt_at}",
        "# HELP evm_height_checker_local_rpc_last_success_timestamp Unix timestamp of the last successful local RPC call.",
        "# TYPE evm_height_checker_local_rpc_last_success_timestamp gauge",
        f"evm_height_checker_local_rpc_last_success_timestamp {local_rpc_last_success_at}",
        "# HELP evm_height_checker_remote_rpc_last_success_timestamp Unix timestamp of the last successful remote RPC call.",
        "# TYPE evm_height_checker_remote_rpc_last_success_timestamp gauge",
        f"evm_height_checker_remote_rpc_last_success_timestamp {remote_rpc_last_success_at}",
        "# HELP evm_height_checker_local_rpc_last_error_timestamp Unix timestamp of the last failed local RPC call.",
        "# TYPE evm_height_checker_local_rpc_last_error_timestamp gauge",
        f"evm_height_checker_local_rpc_last_error_timestamp {local_rpc_last_error_at}",
        "# HELP evm_height_checker_remote_rpc_last_error_timestamp Unix timestamp of the last failed remote RPC call.",
        "# TYPE evm_height_checker_remote_rpc_last_error_timestamp gauge",
        f"evm_height_checker_remote_rpc_last_error_timestamp {remote_rpc_last_error_at}",
    ]
    return "\n".join(lines) + "\n"
