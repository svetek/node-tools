import copy
import json
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPException
from typing import Any

from . import __version__
from .config import Config
from .websocket import WebSocketConnection


class RpcError(Exception):
    pass


class NodeBehind(RpcError):
    def __init__(self, local: int, reference: int, allowed: int) -> None:
        super().__init__(
            f"node behind: node={local}, trusted={reference}, lag={reference - local}, allowed={allowed}"
        )
        self.details = {
            "node_height": local,
            "trusted_height": reference,
            "delta_blocks": reference - local,
            "max_behind_blocks": allowed,
        }


class ReferenceUnavailable(RpcError):
    """A target height was obtained, but no fresh comparison is available."""

    def __init__(self, node_height: int, target_rpc_latency_ms: int, trusted_wait_ms: int) -> None:
        super().__init__("trusted reference unavailable or stale")
        self.node_height = node_height
        self.target_rpc_latency_ms = target_rpc_latency_ms
        self.trusted_wait_ms = trusted_wait_ms


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise RpcError("RPC redirects are disabled")


class RpcClient:
    def __init__(self, config: Config, stop: threading.Event):
        self.config, self.stop = config, stop
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        last = None
        for attempt in range(self.config.retries + 1):
            if self.stop.is_set():
                raise RpcError("stopping")
            try:
                if url.startswith(("ws://", "wss://")):
                    with WebSocketConnection(url, self.config.timeout) as ws:
                        ws.send_json(payload)
                        return self.envelope(ws.receive_json(), payload)
                request = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": f"node-rpc-checker/{__version__}",
                    },
                )
                try:
                    response = self.opener.open(request, timeout=self.config.timeout)
                except urllib.error.HTTPError as exc:
                    # NEAR can return JSON-RPC errors such as UNKNOWN_ACCOUNT with HTTP 4xx.
                    if not 400 <= exc.code < 500 or exc.code == 429:
                        exc.close()
                        raise
                    response = exc
                with response:
                    # read1 returns after one buffered/raw read; a trickling body
                    # cannot keep resetting an inactivity timeout indefinitely.
                    deadline = time.monotonic() + self.config.timeout
                    body = bytearray()
                    while True:
                        if self.stop.is_set():
                            raise RpcError("stopping")
                        if time.monotonic() >= deadline:
                            raise RpcError("HTTP body deadline exceeded")
                        chunk = response.read1(min(65536, 4_194_305 - len(body)))
                        if not chunk:
                            break
                        body.extend(chunk)
                        if len(body) > 4_194_304:
                            raise RpcError("response exceeds 4 MiB")
                return self.envelope(json.loads(body), payload)
            except (OSError, ValueError, RuntimeError, HTTPException, RpcError) as exc:
                last = exc
                if attempt < self.config.retries:
                    self.stop.wait(self.config.retry_delay)
        # Never include URLs or upstream exception messages in RPC errors.
        # Metrics expose origins only, never full endpoint URLs.
        raise RpcError(f"RPC transport/response failure: {type(last).__name__}")

    @staticmethod
    def envelope(result: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if (
            not isinstance(result, dict)
            or result.get("jsonrpc") != "2.0"
            or type(result.get("id")) is not type(payload["id"])
            or result.get("id") != payload["id"]
        ):
            raise RpcError("invalid JSON-RPC envelope")
        if ("result" in result) == ("error" in result):
            raise RpcError("expected exactly one of result/error")
        return result

    def subscription(
        self, url: str, subscribe: dict[str, Any], unsubscribe: dict[str, Any]
    ) -> dict[str, bool]:
        try:
            with WebSocketConnection(url, self.config.timeout) as ws:
                p = copy.deepcopy(subscribe)
                ws.send_json(p)
                r = self.envelope(ws.receive_json(), p)
                sub = r.get("result")
                if not isinstance(sub, str) or not sub:
                    raise RpcError("subscription rejected")
                p = copy.deepcopy(unsubscribe)
                p["params"] = [sub]
                ws.send_json(p)
                while True:
                    r = ws.receive_json()
                    if isinstance(r, dict) and r.get("method") == "eth_subscription":
                        continue
                    r = self.envelope(r, p)
                    if r.get("result") is not True:
                        raise RpcError("unsubscribe rejected")
                    return {"subscription": True}
        except (OSError, ValueError, RuntimeError) as exc:
            raise RpcError(f"WebSocket subscription failed: {type(exc).__name__}") from None
