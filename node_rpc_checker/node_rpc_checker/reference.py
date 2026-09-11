"""Bounded-age, single-flight reference shared by all nodes and transports."""

import threading
import time
from collections.abc import Callable

from .rpc import RpcError


class TrustedReference:
    def __init__(
        self, fetch: Callable[[], int], ttl: float, clock: Callable[[], float] = time.monotonic
    ):
        self.fetch = fetch
        self.ttl = ttl
        self.clock = clock
        self.update_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.started: float | None = None
        self.height: int | None = None
        self.error = False
        self.retry_after = 0.0
        self.attempts = 0
        self.failures = 0
        self.last_duration: float | None = None

    def metrics(self) -> dict[str, float]:
        """Read diagnostics under the state lock only, never the I/O lock."""
        with self.state_lock:
            age = None if self.started is None else max(0.0, self.clock() - self.started)
            values = {
                "reference_up": float(self._cache_is_fresh_unlocked() and not self.error),
                "reference_cache_fresh": float(self._cache_is_fresh_unlocked()),
                "reference_refresh_attempts_total": float(self.attempts),
                "reference_refresh_failures_total": float(self.failures),
            }
            if age is not None:
                values["reference_age_seconds"] = age
            if self.last_duration is not None:
                values["reference_refresh_duration_seconds"] = self.last_duration
            return values

    def last_success(self) -> tuple[int | None, float | None]:
        """Return the last successful observation, including expired data, without I/O."""
        with self.state_lock:
            return self.height, self.started

    def available(self) -> bool:
        """Fresh observation and no failure in the latest refresh attempt."""
        with self.state_lock:
            return not self.error and self._cache_is_fresh_unlocked()

    def has_attempted_refresh(self) -> bool:
        """Whether a refresh has started, not necessarily succeeded."""
        with self.state_lock:
            return self.attempts > 0

    def cache_is_fresh(self) -> bool:
        """Cached observation age only; independent of the latest refresh failure."""
        with self.state_lock:
            return self._cache_is_fresh_unlocked()

    def _cache_is_fresh_unlocked(self) -> bool:
        """Caller must hold state_lock."""
        return (
            self.height is not None
            and self.started is not None
            and self.clock() - self.started < self.ttl
        )

    def snapshot(self) -> tuple[int, float]:
        """Acquire a fresh height and its own observation-start timestamp atomically."""
        self.get()
        with self.state_lock:
            if (
                self.height is None
                or self.error
                or self.started is None
                or self.clock() - self.started >= self.ttl
            ):
                raise RpcError("trusted reference unavailable or stale")
            return self.height, self.started

    def get(self, *, refresh: bool = False) -> int:
        # Readers never queue behind a refresh while the published snapshot is fresh.
        if not refresh:
            with self.state_lock:
                if (
                    self.height is not None
                    and self.started is not None
                    and self.clock() - self.started < self.ttl
                ):
                    return self.height
        # The I/O lock serializes refreshes, not status/metrics reads.
        with self.update_lock:
            with self.state_lock:
                if not refresh and self.error and self.clock() < self.retry_after:
                    raise RpcError("trusted reference unavailable")
                if (
                    not refresh
                    and self.started is not None
                    and self.clock() - self.started < self.ttl
                ):
                    if self.error:
                        raise RpcError("trusted reference unavailable")
                    if self.height is not None:
                        return self.height
                started = self.clock()
                self.attempts += 1
            try:
                height = self.fetch()
            except Exception:
                # Cache failure too, preventing retry storms across all nodes.
                with self.state_lock:
                    self.error = True
                    self.failures += 1
                    self.last_duration = max(0.0, self.clock() - started)
                    self.retry_after = self.clock() + self.ttl
                raise
            with self.state_lock:
                self.last_duration = max(0.0, self.clock() - started)
                if self.clock() - started >= self.ttl:
                    self.error = True
                    self.failures += 1
                    self.retry_after = self.clock() + self.ttl
                    raise RpcError("trusted reference expired during refresh")
                self.height = height
                self.started = started
                self.error = False
                return height
