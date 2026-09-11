import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcError
from node_rpc_checker.service import Checker
from tests.helpers import Fake


class MetricContractTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.fake = Fake()
        self.checker = Checker(
            Config("BASE", {"n": Node("node", "ws://node")}, "trusted"),
            self.fake,
            lambda: self.now,
        )

    def samples(self):
        return {
            line.rsplit(" ", 1)[0]: float(line.rsplit(" ", 1)[1])
            for line in self.checker.metrics().splitlines()
            if line and not line.startswith("#")
        }

    def test_duration_units_and_old_names_absent(self):
        def measured():
            self.now += 1.234
            return {"target_rpc_latency_ms": 123, "trusted_wait_ms": 456}

        row = self.checker.record("n", "http/height", measured)
        samples = self.samples()
        tags = '{chain="BASE",node="n",check="http/height"}'
        for metric, value in (
            ("check_duration_seconds", 1.234),
            ("target_rpc_duration_seconds", 0.123),
            ("reference_wait_duration_seconds", 0.456),
            ("check_last_completed_timestamp_seconds", row["checked_at"]),
        ):
            self.assertAlmostEqual(samples["node_rpc_checker_" + metric + tags], value)
        for old in (
            "reference_valid",
            "latency_ms",
            "target_rpc_latency_ms",
            "trusted_wait_ms",
            "last_attempt_timestamp",
        ):
            self.assertNotIn("node_rpc_checker_" + old, self.checker.metrics())

    def test_verified_zero_on_start_outage_staleness_and_lag(self):
        key = 'node_rpc_checker_height_comparison_verified{chain="BASE",node="n",transport="http"}'
        self.assertEqual(self.samples()[key], 0)
        self.checker.cycle("n")
        self.assertEqual(self.samples()[key], 1)
        self.now = 31
        self.fake.height += 1
        self.checker.cycle("n")
        self.assertEqual(self.samples()[key], 0)
        self.assertEqual(self.checker.response("/readyz/n")[0], 200)
        self.checker.reference.get(refresh=True)
        self.assertEqual(self.samples()[key], 0)
        self.checker.cycle("n")
        self.assertEqual(self.samples()[key], 1)
        self.fake.reference = self.fake.height + 100
        self.checker.reference.get(refresh=True)
        self.checker.cycle("n")
        self.assertEqual(self.samples()[key], 0)
        self.now += 31
        self.assertEqual(self.samples()[key], 0)

    def test_completed_outcomes_and_reads_do_not_increment_counters(self):
        self.checker.cycle("n")
        self.now = 31
        self.fake.height += 1
        self.checker.cycle("n")
        self.assertEqual(self.checker.check_results["n", "http/height", "success", "none"], 1)
        self.assertEqual(
            self.checker.check_results["n", "http/height", "unverified", "reference_error"], 1
        )
        with patch.object(self.checker.engine, "height", side_effect=RpcError("offline")):
            self.checker.record("n", "http/height", lambda: self.checker.compare("node"))
        self.assertEqual(self.checker.check_results["n", "http/height", "failure", "rpc_error"], 1)
        with patch.object(self.checker, "internal_error"):
            self.checker.record("n", "http/height", lambda: {"ok": False})
        self.assertEqual(
            self.checker.check_results["n", "http/height", "failure", "internal_error"], 1
        )
        before = dict(self.checker.check_results)
        self.now += 100
        for _ in range(5):
            self.checker.metrics()
            self.checker.response("/status/n")
        self.assertEqual(before, self.checker.check_results)
        self.assertIn("# TYPE node_rpc_checker_check_results_total counter", self.checker.metrics())

    def test_counter_updates_are_thread_safe(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(
                pool.map(
                    lambda _: self.checker.record("n", "http/chain-id", lambda: {}), range(100)
                )
            )
        self.assertEqual(self.checker.check_results["n", "http/chain-id", "success", "none"], 100)

    def test_cache_fresh_is_not_reference_up(self):
        self.checker.reference.get()
        with patch.object(self.checker.reference, "fetch", side_effect=RpcError("offline")):
            with self.assertRaises(RpcError):
                self.checker.reference.get(refresh=True)
        samples = self.samples()
        self.assertEqual(samples['node_rpc_checker_reference_cache_fresh{chain="BASE"}'], 1)
        self.assertEqual(samples['node_rpc_checker_reference_up{chain="BASE"}'], 0)
