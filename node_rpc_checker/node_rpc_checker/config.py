import json
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlsplit

CHAINS = (
    "NEAR",
    "NEART",
    "ETH1",
    "SEP1",
    "HOL1",
    "BASE",
    "BASES",
    "ARBITRUM",
    "ARBITRUMN",
    "ARBITRUMS",
)


def validate_url(url: str, schemes: tuple[str, ...]) -> None:
    if (
        not isinstance(url, str)
        or len(url) > 8192
        or any(ord(c) <= 32 or ord(c) == 127 for c in url)
    ):
        raise ValueError("RPC URL contains whitespace/control characters or is too long")
    try:
        p = urlsplit(url)
        port = p.port
        if (
            p.scheme not in schemes
            or not p.hostname
            or p.fragment
            or p.username is not None
            or p.password is not None
            or port == 0
            or "\\" in p.netloc
        ):
            raise ValueError
        url.encode("ascii")
    except (ValueError, UnicodeError):
        raise ValueError("invalid RPC URL; use ASCII URL without userinfo or fragments") from None


@dataclass(frozen=True)
class Node:
    rpc_url: str
    websocket_url: str = ""
    addons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    chain_id: str
    nodes: dict[str, Node]
    trusted: str
    poll: float = 5
    deep_interval: float = 60
    ttl: float = 30
    deep_ttl: float = 180
    timeout: float = 3
    retries: int = 2
    retry_delay: float = 0.5
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 4
    trusted_ttl: float = 30
    max_behind_blocks: int = 0
    trusted_refresh_interval: float = 5
    deep_workers: int = 2
    progress_ttl: float = 30
    trusted_timeout: float = 5

    def __post_init__(self) -> None:
        if type(self.max_behind_blocks) is not int or self.max_behind_blocks < 0:
            raise ValueError("MAX_BEHIND_BLOCKS must be a nonnegative integer")

    @classmethod
    def from_env(cls) -> Self:
        chain_id = os.getenv("CHAIN_ID", "").upper()
        if chain_id not in CHAINS:
            raise ValueError("set CHAIN_ID to one of: " + ", ".join(CHAINS))
        single, multi = os.getenv("NODE_RPC_URL", ""), os.getenv("NODES_JSON", "")
        if bool(single) == bool(multi):
            raise ValueError("set exactly one of NODE_RPC_URL and NODES_JSON")
        raw = (
            json.loads(multi)
            if multi
            else {
                "default": {
                    "rpc_url": single,
                    "websocket_url": os.getenv("WEBSOCKET_URL", ""),
                    "addons": [s.strip() for s in os.getenv("ADDONS", "").split(",") if s.strip()],
                }
            }
        )
        if not isinstance(raw, dict) or not 1 <= len(raw) <= 64:
            raise ValueError("NODES_JSON must contain 1–64 nodes")
        nodes = {}
        for name, value in raw.items():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
                raise ValueError("invalid node name")
            if not isinstance(value, dict) or not isinstance(value.get("rpc_url"), str):
                raise ValueError("each node requires rpc_url")
            if set(value) - {"rpc_url", "websocket_url", "addons"}:
                raise ValueError("unknown NODES_JSON option")
            addons = value.get("addons", [])
            ws = value.get("websocket_url", "")
            if (
                not isinstance(addons, list)
                or any(not isinstance(a, str) for a in addons)
                or not isinstance(ws, str)
            ):
                raise ValueError("addons must be a list of strings, websocket_url a string")
            if ws:
                validate_url(ws, ("ws", "wss"))
            nodes[name] = Node(value["rpc_url"], ws, tuple(dict.fromkeys(addons)))
        defaults = {
            "NEAR": "https://rpc.mainnet.near.org",
            "NEART": "https://rpc.testnet.near.org",
            "BASE": "https://mainnet.base.org",
            "BASES": "https://sepolia.base.org",
        }
        trusted = os.getenv("TRUSTED_RPC_URL", defaults.get(chain_id, ""))
        for url in [trusted, *(n.rpc_url for n in nodes.values())]:
            validate_url(url, ("http", "https"))
        values: dict[str, Any] = {}
        if "REFERENCE_GRACE_SECONDS" in os.environ:
            legacy_grace = float(os.environ["REFERENCE_GRACE_SECONDS"])
            if not math.isfinite(legacy_grace) or legacy_grace < 0:
                raise ValueError("invalid REFERENCE_GRACE_SECONDS")
            logging.warning("REFERENCE_GRACE_SECONDS is deprecated and ignored")
        for field, env, default in [
            ("poll", "POLL_INTERVAL_SECONDS", 5),
            ("deep_interval", "DEEP_CHECK_INTERVAL_SECONDS", 60),
            ("ttl", "STATE_TTL_SECONDS", 30),
            ("deep_ttl", "DEEP_STATE_TTL_SECONDS", 180),
            ("timeout", "RPC_TIMEOUT_SECONDS", 3),
            ("trusted_timeout", "TRUSTED_RPC_TIMEOUT_SECONDS", 5),
            ("retry_delay", "RETRY_DELAY_SECONDS", 0.5),
            ("trusted_ttl", "TRUSTED_STATE_TTL_SECONDS", 30),
            ("trusted_refresh_interval", "TRUSTED_REFRESH_INTERVAL_SECONDS", 5),
            ("progress_ttl", "NODE_PROGRESS_TTL_SECONDS", 30),
        ]:
            v = float(os.getenv(env, str(default)))
            if not math.isfinite(v) or v < 0 or (v == 0 and field != "retry_delay"):
                raise ValueError(f"invalid {env}")
            values[field] = v
        retries = int(os.getenv("RPC_RETRY_COUNT", "2"))
        port = int(os.getenv("HTTP_PORT", "8080"))
        workers = int(os.getenv("CHECK_WORKERS", "4"))
        deep_workers = int(os.getenv("DEEP_CHECK_WORKERS", "2"))
        if not 1 <= deep_workers <= 32:
            raise ValueError("DEEP_CHECK_WORKERS must be between 1 and 32")
        raw_max_behind = os.getenv("MAX_BEHIND_BLOCKS", "0").strip()
        if not re.fullmatch(r"[0-9]+", raw_max_behind):
            raise ValueError("MAX_BEHIND_BLOCKS must be a nonnegative integer")
        max_behind_blocks = int(raw_max_behind)
        if not 1 <= workers <= 32:
            raise ValueError("CHECK_WORKERS must be between 1 and 32")
        if not 0 <= retries <= 5 or not 1 <= port <= 65535:
            raise ValueError("invalid retries or HTTP_PORT")
        if values["deep_ttl"] <= values["deep_interval"]:
            raise ValueError("DEEP_STATE_TTL_SECONDS must exceed DEEP_CHECK_INTERVAL_SECONDS")
        if values["trusted_ttl"] > values["ttl"]:
            raise ValueError("TRUSTED_STATE_TTL_SECONDS must not exceed STATE_TTL_SECONDS")
        if values["trusted_refresh_interval"] >= values["trusted_ttl"]:
            raise ValueError(
                "TRUSTED_REFRESH_INTERVAL_SECONDS must be less than TRUSTED_STATE_TTL_SECONDS"
            )
        nominal_fetch = 2 * (
            (retries + 1) * values["trusted_timeout"] + retries * values["retry_delay"]
        )
        if values["trusted_ttl"] <= nominal_fetch + values["trusted_refresh_interval"]:
            logging.warning(
                "Trusted TTL leaves insufficient nominal refresh/retry margin; "
                "slow references may disable fresh lag validation"
            )
        return cls(
            chain_id,
            nodes,
            trusted,
            **values,
            retries=retries,
            host=os.getenv("HTTP_HOST", "0.0.0.0"),
            port=port,
            workers=workers,
            deep_workers=deep_workers,
            max_behind_blocks=max_behind_blocks,
        )
