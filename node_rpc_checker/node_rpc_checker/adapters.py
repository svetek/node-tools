import json
from typing import Any

from .rpc import RpcError


class Near:
    websocket = False

    def check_status(self, response: dict[str, Any]) -> None:
        if response.get("result", {}).get("sync_info", {}).get("syncing") is not False:
            raise RpcError("node is syncing or sync status missing")

    def subscription_requests(
        self, directives: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raise ValueError("WebSocket is not supported for NEAR")


class Evm:
    websocket = True

    def check_status(self, response: dict[str, Any]) -> None:
        pass

    def subscription_requests(
        self, directives: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        subscribe = directives.get("SUBSCRIBE", {})
        unsubscribe = directives.get("UNSUBSCRIBE", {})
        method = subscribe.get("api_name")
        if not isinstance(method, str) or not method:
            raise ValueError("missing SUBSCRIBE api_name")
        if subscribe.get("function_template"):
            raise ValueError("unsupported SUBSCRIBE template; EVM adapter supplies newHeads")
        try:
            request = json.loads(unsubscribe["function_template"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("missing or invalid UNSUBSCRIBE template") from None
        if (
            not isinstance(request, dict)
            or request.get("jsonrpc") != "2.0"
            or not isinstance(request.get("method"), str)
            or not request["method"]
            or request["method"] != unsubscribe.get("api_name")
            or request.get("params") != ["%s"]
            or type(request.get("id")) not in (int, str)
        ):
            raise ValueError("unsupported UNSUBSCRIBE template")
        return {"jsonrpc": "2.0", "id": 1, "method": method, "params": ["newHeads"]}, request


class Iota(Evm):
    def subscription_requests(
        self, directives: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        subscribe, unsubscribe = super().subscription_requests(directives)
        method = subscribe["method"]
        if method not in ("iotax_subscribeTransaction", "iotax_subscribeEvent"):
            raise ValueError("unsupported IOTA subscription")
        if unsubscribe["method"] != method.replace("_subscribe", "_unsubscribe"):
            raise ValueError("mismatched IOTA unsubscribe method")
        key = "FromAddress" if method.endswith("Transaction") else "Sender"
        subscribe["params"] = [{key: "0x" + "0" * 64}]
        return subscribe, unsubscribe


class Tendermint:
    websocket = True

    def check_status(self, response: dict[str, Any]) -> None:
        if response.get("result", {}).get("sync_info", {}).get("catching_up") is not False:
            raise RpcError("node is syncing or sync status missing")

    def subscription_requests(
        self, directives: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if directives.get("SUBSCRIBE", {}).get("api_name") != "subscribe":
            raise ValueError("missing Tendermint SUBSCRIBE directive")
        if directives.get("UNSUBSCRIBE", {}).get("api_name") != "unsubscribe":
            raise ValueError("missing Tendermint UNSUBSCRIBE directive")
        params = {"query": "tm.event='NewBlock'"}
        return (
            {"jsonrpc": "2.0", "id": 1, "method": "subscribe", "params": params},
            {"jsonrpc": "2.0", "id": 2, "method": "unsubscribe", "params": params},
        )


class Tezos:
    websocket = False

    def check_status(self, response: dict[str, Any]) -> None:
        # Lava's Tezos spec has no separate syncing-status verification.
        pass

    def subscription_requests(
        self, directives: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raise ValueError("WebSocket is not supported for Tezos")


def adapter_for(chain_id: str) -> Near | Evm | Tendermint | Tezos:
    if chain_id in ("IOTA", "IOTAT"):
        return Iota()
    if chain_id in ("TEZOS", "TEZOST"):
        return Tezos()
    if chain_id in ("COSMOSHUB", "COSMOSHUBT"):
        return Tendermint()
    return Near() if chain_id in ("NEAR", "NEART") else Evm()
