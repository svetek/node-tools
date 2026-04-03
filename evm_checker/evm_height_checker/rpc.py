from __future__ import annotations

import json
import urllib.error
import urllib.request


class RpcError(RuntimeError):
    """Raised when JSON-RPC response is invalid."""


class RpcClient:
    def __init__(self, timeout_seconds: float, user_agent: str = "evm-height-checker/0.1") -> None:
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
