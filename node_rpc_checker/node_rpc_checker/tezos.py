"""Tezos REST responses use the JSON document itself, without a RPC envelope."""

from typing import Any

from .engine import Engine


class TezosEngine(Engine):
    def request(self, url: str, pd: dict, template: str) -> dict[str, Any]:
        return {"result": self.client.rest(url, template, pd.get("http_method", "GET"))}
