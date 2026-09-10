from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True)
class NodeConfig:
    name: str
    rpc_url: str
    websocket_url: str = ""


_NODE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _nodes_json() -> tuple[NodeConfig, ...]:
    raw = os.getenv("NODES_JSON", "").strip()
    if not raw:
        return ()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"NODES_JSON must be valid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict) or not payload:
        raise ConfigError("NODES_JSON must be a non-empty object")

    nodes: list[NodeConfig] = []
    for name, value in payload.items():
        if not isinstance(name, str) or not _NODE_NAME_RE.fullmatch(name):
            raise ConfigError(f"invalid node name in NODES_JSON: {name!r}")
        if not isinstance(value, dict):
            raise ConfigError(f"NODES_JSON entry {name!r} must be an object")

        rpc_url = value.get("rpc_url", "")
        websocket_url = value.get("websocket_url", "")
        if not isinstance(rpc_url, str) or not rpc_url.strip():
            raise ConfigError(f"NODES_JSON entry {name!r} requires rpc_url")
        if not isinstance(websocket_url, str):
            raise ConfigError(
                f"NODES_JSON websocket_url for {name!r} must be a string"
            )

        nodes.append(
            NodeConfig(
                name=name,
                rpc_url=rpc_url.strip(),
                websocket_url=websocket_url.strip(),
            )
        )
    return tuple(nodes)


def _required_str(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    return value


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    return value


@dataclass(frozen=True)
class Config:
    local_rpc_url: str
    remote_rpc_url: str
    rpc_user_agent: str
    max_behind_blocks: int
    poll_interval_seconds: float
    rpc_timeout_seconds: float
    rpc_retry_count: int
    retry_delay_seconds: float
    state_ttl_seconds: float
    http_host: str
    http_port: int
    websocket_url: str = ""
    nodes: tuple[NodeConfig, ...] = ()

    @classmethod
    def from_env(cls) -> "Config":
        poll_interval_seconds = _float("POLL_INTERVAL_SECONDS", 5.0)
        state_ttl_seconds = _float(
            "STATE_TTL_SECONDS",
            max(poll_interval_seconds * 3, 30.0),
        )

        nodes = _nodes_json()
        local_rpc_url = os.getenv("LOCAL_RPC_URL", "").strip()
        if nodes and local_rpc_url:
            raise ConfigError("set either NODES_JSON or LOCAL_RPC_URL, not both")
        if not nodes and not local_rpc_url:
            raise ConfigError("LOCAL_RPC_URL is required when NODES_JSON is not set")

        config = cls(
            local_rpc_url=local_rpc_url,
            remote_rpc_url=_required_str("REMOTE_RPC_URL"),
            rpc_user_agent=os.getenv("RPC_USER_AGENT", "evm-height-checker/0.2").strip()
            or "evm-height-checker/0.2",
            max_behind_blocks=_int("MAX_BEHIND_BLOCKS", 0),
            poll_interval_seconds=poll_interval_seconds,
            rpc_timeout_seconds=_float("RPC_TIMEOUT_SECONDS", 3.0),
            rpc_retry_count=_int("RPC_RETRY_COUNT", 2),
            retry_delay_seconds=_float("RETRY_DELAY_SECONDS", 0.5),
            state_ttl_seconds=state_ttl_seconds,
            http_host=os.getenv("HTTP_HOST", "0.0.0.0").strip() or "0.0.0.0",
            http_port=_int("HTTP_PORT", 8080),
            websocket_url=os.getenv("WEBSOCKET_URL", "").strip(),
            nodes=nodes,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.max_behind_blocks < 0:
            raise ConfigError("MAX_BEHIND_BLOCKS must be >= 0")
        if self.poll_interval_seconds <= 0:
            raise ConfigError("POLL_INTERVAL_SECONDS must be > 0")
        if self.rpc_timeout_seconds <= 0:
            raise ConfigError("RPC_TIMEOUT_SECONDS must be > 0")
        if self.rpc_retry_count < 0:
            raise ConfigError("RPC_RETRY_COUNT must be >= 0")
        if self.retry_delay_seconds < 0:
            raise ConfigError("RETRY_DELAY_SECONDS must be >= 0")
        if self.state_ttl_seconds <= 0:
            raise ConfigError("STATE_TTL_SECONDS must be > 0")
        if not (1 <= self.http_port <= 65535):
            raise ConfigError("HTTP_PORT must be between 1 and 65535")

    def configured_nodes(self) -> tuple[NodeConfig, ...]:
        if self.nodes:
            return self.nodes
        return (
            NodeConfig(
                name="default",
                rpc_url=self.local_rpc_url,
                websocket_url=self.websocket_url,
            ),
        )
