"""Bounded round-robin scheduling, with no overlapping attempts per check."""

import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor


def run_checks(
    jobs: list[tuple[str, str, Callable]],
    record: Callable,
    report_error: Callable,
    workers: int,
    interval: float,
    stop: threading.Event,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    pending = deque((job, 0.0) for job in jobs)
    active: dict[Future, tuple[str, str, Callable]] = {}
    wake = threading.Event()

    def execute(job):
        if not stop.is_set():
            record(*job)
        return clock()

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc-check") as pool:
        while not stop.is_set():
            wake.clear()
            for future in list(active):
                if future.done():
                    job = active.pop(future)
                    try:
                        completed = future.result()
                    except Exception as exc:
                        report_error(job[0], job[1], exc)
                        completed = clock()
                    pending.append((job, completed + interval))
            for _ in range(len(pending)):
                if stop.is_set() or len(active) >= workers:
                    break
                job, due = pending.popleft()
                if clock() < due:
                    pending.append((job, due))
                    continue
                future = pool.submit(execute, job)
                active[future] = job
                future.add_done_callback(lambda _: wake.set())
            # No unbounded executor queue; stop is observed within 100 ms.
            # Wake immediately on completion, without imposing a 10 Hz batch cap.
            wake.wait(0.1)
        for future in active:
            future.cancel()
        # Drain running work and account for errors even during shutdown.
        for future, job in active.items():
            if not future.cancelled():
                try:
                    future.result()
                except Exception as exc:
                    report_error(job[0], job[1], exc)
