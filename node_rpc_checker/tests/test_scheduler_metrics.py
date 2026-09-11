import threading
import time
import unittest
from unittest.mock import Mock, patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.reference import TrustedReference
from node_rpc_checker.rpc import RpcError
from node_rpc_checker.scheduler import run_checks
from node_rpc_checker.service import Checker
from tests.helpers import Fake


class ReferenceDiagnosticsTests(unittest.TestCase):
    def test_proactive_recovery_before_backoff_expires(self):
        now = [0.0]
        checker = Checker(Config("BASE", {"n": Node("node")}, "trusted"), Fake(), lambda: now[0])
        checker.cycle("n", mode="readyz")
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        now[0] = 5
        with patch.object(checker.reference, "fetch", side_effect=RpcError("502")):
            with self.assertRaises(RpcError):
                checker.reference.get(refresh=True)
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        now[0] = 30
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        for _ in range(64):
            with self.assertRaises(RpcError):
                checker.reference.get()
        self.assertEqual(checker.reference.metrics()["reference_refresh_attempts_total"], 2)

        class Stop:
            done = False

            def is_set(self):
                return self.done

            def wait(self, interval):
                self.done = True

        now[0] = 31
        checker.run_reference(Stop())
        checker.cycle("n", mode="readyz")
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        stats = checker.reference.metrics()
        self.assertEqual(stats["reference_refresh_attempts_total"], 3)
        self.assertEqual(stats["reference_refresh_failures_total"], 1)
        self.assertEqual(stats["reference_cache_fresh"], 1)
        self.assertIn(
            "# TYPE node_rpc_checker_reference_refresh_failures_total counter", checker.metrics()
        )

    def test_metrics_are_nonblocking_and_expiry_counts_once(self):
        now = [0.0]
        entered, release = threading.Event(), threading.Event()

        def fetch():
            entered.set()
            release.wait(3)
            now[0] = 31
            return 1

        reference = TrustedReference(fetch, 30, lambda: now[0])
        errors = []

        def update():
            try:
                reference.get()
            except RpcError as error:
                errors.append(error)

        thread = threading.Thread(target=update)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            stats = reference.metrics()
            self.assertEqual(stats["reference_refresh_attempts_total"], 1)
            self.assertEqual(stats["reference_refresh_failures_total"], 0)
            self.assertNotIn("reference_age_seconds", stats)
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(len(errors), 1)
        stats = reference.metrics()
        self.assertEqual(stats["reference_refresh_failures_total"], 1)
        self.assertEqual(stats["reference_refresh_duration_seconds"], 31)
        self.assertEqual(stats["reference_cache_fresh"], 0)


class GlobalSchedulerTests(unittest.TestCase):
    def test_64_nodes_bounded_fair_and_no_overlap(self):
        checker = Checker(
            Config("NEAR", {str(i): Node("node") for i in range(64)}, "trusted", poll=0.01),
            Fake("NEAR"),
        )
        # Two tasks per node exercise interleaving and repeated scheduling.
        checker.plans = {
            name: {str(i): ("readyz", lambda: {}) for i in range(2)}
            for name in checker.config.nodes
        }
        stop, all_seen, release = threading.Event(), threading.Event(), threading.Event()
        lock = threading.Lock()
        active, seen, threads = set(), set(), set()
        violations = []
        peak = [0]

        def record(name, key, fn):
            with lock:
                if (name, key) in active:
                    violations.append("overlap")
                active.add((name, key))
                threads.add(threading.get_ident())
                peak[0] = max(peak[0], len(active))
                seen.add((name, key))
                if len(seen) == 128:
                    all_seen.set()
            if name == "0":
                release.wait(8)
            with lock:
                active.remove((name, key))
            return {}

        thread = threading.Thread(target=checker.run_mode, args=("readyz", stop))
        with patch.object(checker, "record", side_effect=record):
            thread.start()
            try:
                self.assertTrue(all_seen.wait(7), "one slow node starved other nodes")
            finally:
                stop.set()
                release.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertLessEqual(peak[0], 4)
        self.assertLessEqual(len(threads), 4)
        self.assertEqual(violations, [])

    def test_interval_from_completion_stop_and_error_accounting(self):
        stop = threading.Event()
        times = []
        report = Mock()

        def record(*args):
            times.append(time.monotonic())
            if len(times) == 2:
                stop.set()
            raise TypeError("internal")

        thread = threading.Thread(
            target=run_checks, args=([("n", "k", lambda: {})], record, report, 1, 0.15, stop)
        )
        thread.start()
        thread.join(3)
        if thread.is_alive():
            stop.set()
            thread.join(2)
            self.fail("scheduler did not stop")
        self.assertEqual(len(times), 2)
        self.assertGreaterEqual(times[1] - times[0], 0.15)
        self.assertEqual(report.call_count, 2)

    def test_stop_prevents_pending_work(self):
        stop = threading.Event()
        calls = []

        def record(name, key, fn):
            calls.append(key)
            stop.set()

        run_checks([("n", str(i), lambda: {}) for i in range(64)], record, Mock(), 1, 5, stop)
        self.assertEqual(calls, ["0"])

    def test_deep_workers_validation(self):
        import os

        for value in ("0", "33", "x"):
            with patch.dict(
                os.environ,
                {"CHAIN_ID": "BASE", "NODE_RPC_URL": "http://node", "DEEP_CHECK_WORKERS": value},
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()
