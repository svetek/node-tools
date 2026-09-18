"""Cosmos REST and native gRPC transports and spec-backed checks."""

import json
import time
import urllib.error
import urllib.request
from http.client import HTTPException
from urllib.parse import urlsplit

from . import __version__
from .engine import Engine
from .rpc import RpcEndpointError, RpcError


def rest_call(client, url, path, method="GET"):
    last = None
    for attempt in range(client.config.retries + 1):
        if client.stop.is_set():
            raise RpcError("stopping")
        try:
            request = urllib.request.Request(
                url.rstrip("/") + path,
                data=b"{}" if method == "POST" else None,
                method=method,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"node-rpc-checker/{__version__}",
                },
            )
            try:
                response = client.opener.open(request, timeout=client.config.timeout)
            except urllib.error.HTTPError as exc:
                if method == "POST" and path == "/cosmos/tx/v1beta1/simulate" and exc.code == 400:
                    response = exc
                elif exc.code in (400, 404) and "/blocks/" in path:
                    exc.close()
                    raise RpcError("requested Cosmos block unavailable") from None
                else:
                    exc.close()
                    raise
            with response:
                deadline = time.monotonic() + client.config.timeout
                body = bytearray()
                while True:
                    if client.stop.is_set() or time.monotonic() >= deadline:
                        raise TimeoutError("REST body deadline")
                    chunk = response.read1(min(65536, 4194305 - len(body)))
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > 4194304:
                        raise ValueError("REST response too large")
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ValueError("invalid REST response")
                return result
        except (OSError, ValueError, RuntimeError, HTTPException) as exc:
            last = exc
            if attempt < client.config.retries:
                client.stop.wait(client.config.retry_delay)
    raise RpcEndpointError(f"REST transport/response failure: {type(last).__name__}")


def grpc_call(client, url, method, payload):
    import grpc  # type: ignore[import-untyped]
    from google.protobuf.message import DecodeError  # type: ignore[import-untyped]

    from .cosmos_proto import codec

    parsed = urlsplit(url)
    host = f"[{parsed.hostname}]" if ":" in (parsed.hostname or "") else parsed.hostname
    target = f"{host}:{parsed.port or (443 if parsed.scheme == 'grpcs' else 9090)}"
    data, decode = codec(method, payload)
    options = (
        ("grpc.max_receive_message_length", 4194304),
        ("grpc.primary_user_agent", f"node-rpc-checker/{__version__}"),
        ("grpc.enable_retries", 0),
    )
    last = None
    for attempt in range(client.config.retries + 1):
        if client.stop.is_set():
            raise RpcError("stopping")
        channel = (
            grpc.secure_channel(target, grpc.ssl_channel_credentials(), options=options)
            if parsed.scheme == "grpcs"
            else grpc.insecure_channel(target, options=options)
        )
        try:
            with channel:
                raw = channel.unary_unary("/" + method)(data, timeout=client.config.timeout)
                return decode(raw)
        except grpc.RpcError as exc:
            if exc.code() in (
                grpc.StatusCode.NOT_FOUND,
                grpc.StatusCode.INVALID_ARGUMENT,
                grpc.StatusCode.OUT_OF_RANGE,
            ):
                raise RpcError("Cosmos gRPC request rejected") from None
            last = exc
        except (ValueError, DecodeError) as exc:
            last = exc
        if attempt < client.config.retries:
            client.stop.wait(client.config.retry_delay)
    raise RpcEndpointError(f"gRPC transport/response failure: {type(last).__name__}")


class CosmosApiEngine(Engine):
    def request(self, url: str, pd: dict, template: str) -> dict:
        if self.spec.collection_type[0] == "rest":
            data = self.client.rest(url, template, pd.get("http_method", "GET"))
            sdk_block = "sdk_block"
        else:
            data = self.client.grpc(url, pd["api_name"], json.loads(template) if template else {})
            sdk_block = "sdkBlock"
        # SDK >=0.47 may return only sdk_block; Lava templates still use block.
        if not data.get("block") and data.get(sdk_block):
            data = {**data, "block": data[sdk_block]}
        return {"result": data}

    def verify(self, url, rule):
        result = super().verify(url, rule)
        if rule.key == "chain-id":
            syncing = (
                self.client.rest(url, "/cosmos/base/tendermint/v1beta1/syncing")
                if self.spec.collection_type[0] == "rest"
                else self.client.grpc(url, "cosmos.base.tendermint.v1beta1.Service/GetSyncing", {})
            )
            if syncing.get("syncing") is not False:
                raise RpcError("node is syncing or sync status missing")
        return result
