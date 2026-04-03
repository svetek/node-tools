from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


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

    @classmethod
    def from_env(cls) -> "Config":
        poll_interval_seconds = _float("POLL_INTERVAL_SECONDS", 5.0)
        state_ttl_seconds = _float(
            "STATE_TTL_SECONDS",
            max(poll_interval_seconds * 3, 30.0),
        )

        config = cls(
            local_rpc_url=_required_str("LOCAL_RPC_URL"),
            remote_rpc_url=_required_str("REMOTE_RPC_URL"),
            rpc_user_agent=os.getenv("RPC_USER_AGENT", "evm-height-checker/0.1").strip()
            or "evm-height-checker/0.1",
            max_behind_blocks=_int("MAX_BEHIND_BLOCKS", 0),
            poll_interval_seconds=poll_interval_seconds,
            rpc_timeout_seconds=_float("RPC_TIMEOUT_SECONDS", 3.0),
            rpc_retry_count=_int("RPC_RETRY_COUNT", 2),
            retry_delay_seconds=_float("RETRY_DELAY_SECONDS", 0.5),
            state_ttl_seconds=state_ttl_seconds,
            http_host=os.getenv("HTTP_HOST", "0.0.0.0").strip() or "0.0.0.0",
            http_port=_int("HTTP_PORT", 8080),
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
