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

    def valid(self) -> bool:
        with self.state_lock:
            return (
                not self.error
                and self.height is not None
                and self.started is not None
                and self.clock() - self.started < self.ttl
            )

    def get(self) -> int:
        # The I/O lock serializes refreshes, not status/metrics reads.
        with self.update_lock:
            with self.state_lock:
                if self.error and self.clock() < self.retry_after:
                    raise RpcError("trusted reference unavailable")
                if self.started is not None and self.clock() - self.started < self.ttl:
                    if self.error:
                        raise RpcError("trusted reference unavailable")
                    if self.height is not None:
                        return self.height
                self.started = self.clock()
                self.height = None
                self.error = True
            try:
                height = self.fetch()
            except Exception:
                # Cache failure too, preventing retry storms across all nodes.
                with self.state_lock:
                    self.retry_after = self.clock() + self.ttl
                raise
            with self.state_lock:
                if self.clock() - self.started >= self.ttl:
                    self.retry_after = self.clock() + self.ttl
                    raise RpcError("trusted reference expired during refresh")
                self.height = height
                self.error = False
                return height
