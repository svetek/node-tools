from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request


class RpcError(RuntimeError):
    """Raised when JSON-RPC response is invalid."""


class RpcClient:
    def __init__(self, timeout_seconds: float, user_agent: str = "evm-height-checker/0.2") -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def get_block_number(self, url: str) -> int:
        request_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": 1,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url=url,
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RpcError(f"request failed for {url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RpcError(f"invalid JSON from {url}") from exc

        if "error" in payload:
            raise RpcError(f"rpc error from {url}: {payload['error']}")

        result = payload.get("result")
        if not isinstance(result, str):
            raise RpcError(f"missing hex result from {url}")

        try:
            return int(result, 16)
        except ValueError as exc:
            raise RpcError(f"invalid block number '{result}' from {url}") from exc


class WebSocketClient:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def check_handshake(self, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise RpcError(f"invalid WebSocket URL: {url}")

        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        host_header = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{port}"
        websocket_key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {websocket_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")

        try:
            with socket.create_connection(
                (parsed.hostname, port), timeout=self.timeout_seconds
            ) as raw_socket:
                connection = raw_socket
                if parsed.scheme == "wss":
                    context = ssl.create_default_context()
                    connection = context.wrap_socket(
                        raw_socket, server_hostname=parsed.hostname
                    )
                connection.settimeout(self.timeout_seconds)
                connection.sendall(request)
                response = b""
                while b"\r\n\r\n" not in response and len(response) < 16384:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    response += chunk
        except (OSError, ssl.SSLError) as exc:
            raise RpcError(f"WebSocket handshake failed for {url}: {exc}") from exc

        status_line = response.split(b"\r\n", 1)[0]
        if not status_line.startswith(b"HTTP/1.1 101"):
            decoded_status = status_line.decode("ascii", errors="replace")
            raise RpcError(
                f"WebSocket handshake failed for {url}: expected HTTP 101, got {decoded_status!r}"
            )
