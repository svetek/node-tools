import unittest
from unittest.mock import patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcError
from node_rpc_checker.service import Checker
from tests.helpers import Fake


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.fake = Fake("NEAR")
        self.fake.archive = True
        self.checker = Checker(
            Config("NEAR", {"n": Node("node")}, "trusted"), self.fake, lambda: self.now
        )
        self.checker.cycle("n")

    def status(self, mode):
        return self.checker.response(f"/{mode}/n")[0]

    def outage(self):
        self.checker.reference.fetch = lambda: (_ for _ in ()).throw(RpcError("offline"))

    def advance(self, time):
        self.now = time
        self.fake.height += 1
        self.checker.cycle("n")

    def test_outage_has_no_deadline_and_delta_keeps_decreasing(self):
        reference = self.fake.reference
        self.outage()
        deltas = []
        for time in (31, 149, 150, 3600, 86400):
            self.advance(time)
            for mode in ("readyz", "pruning", "archive"):
                self.assertEqual(self.status(mode), 200)
            row = self.checker.snapshot("n")["n"]["http/height"]
            self.assertFalse(row["reference_fresh"])
            self.assertEqual(row["trusted_height"], reference)
            self.assertEqual(row["delta_blocks"], reference - self.fake.height)
            deltas.append(row["delta_blocks"])
        self.assertTrue(all(b < a for a, b in zip(deltas, deltas[1:])))
        metrics = self.checker.metrics()
        self.assertIn(
            'node_rpc_checker_rpc_up{chain="NEAR",node="",role="trusted",transport="http"} 0',
            metrics,
        )
        self.assertIn(
            'node_rpc_checker_rpc_up{chain="NEAR",node="n",role="backend",transport="http"} 1',
            metrics,
        )

    def test_cold_start_without_trusted_has_unknown_delta(self):
        self.checker = Checker(
            Config("NEAR", {"n": Node("node")}, "trusted"), self.fake, lambda: self.now
        )
        self.outage()
        self.checker.cycle("n")
        self.assertEqual(self.status("archive"), 200)
        row = self.checker.snapshot("n")["n"]["http/height"]
        self.assertNotIn("delta_blocks", row)
        self.assertNotIn("trusted_height", row)

    def test_stall_and_stale_local_checks_still_fail(self):
        self.outage()
        self.advance(31)
        self.now = 61
        self.checker.cycle("n")
        self.assertEqual(self.status("readyz"), 503)
        self.advance(62)
        self.assertEqual(self.status("readyz"), 200)
        self.now = 93
        self.assertEqual(self.status("readyz"), 503)

    def test_target_failure_not_masked_and_local_recovery_suffices(self):
        self.outage()
        self.advance(31)
        with patch.object(self.checker.engine, "height", side_effect=RpcError("offline")):
            self.advance(32)
        self.assertEqual(self.status("readyz"), 503)
        self.assertIn(
            'node_rpc_checker_rpc_up{chain="NEAR",node="n",role="backend",transport="http"} 0',
            self.checker.metrics(),
        )
        self.advance(33)
        self.assertEqual(self.status("archive"), 200)

    def test_shards_and_regressions_still_fail(self):
        self.outage()
        self.advance(31)
        self.fake.shard = "UNAVAILABLE_SHARD"
        self.advance(32)
        self.assertEqual(self.status("archive"), 503)
        self.fake.shard = "UNKNOWN_ACCOUNT"
        self.fake.height -= 10
        self.advance(33)
        self.assertEqual(self.status("readyz"), 503)

    def test_recovery_does_not_drop_availability_before_next_check(self):
        self.outage()
        self.advance(31)
        self.checker.reference.fetch = lambda: self.fake.reference
        self.checker.reference.get(refresh=True)
        self.assertEqual(self.status("archive"), 200)
        self.assertTrue(self.checker.response("/status/n")[1]["nodes"]["n"]["degraded"])
        self.advance(32)
        self.assertFalse(self.checker.response("/status/n")[1]["nodes"]["n"]["degraded"])

    def test_recovered_trusted_reenables_lag_limit_but_rpc_stays_up(self):
        self.outage()
        self.advance(31)
        self.checker.reference.fetch = lambda: self.fake.height + 100
        self.checker.reference.get(refresh=True)
        self.advance(32)
        self.assertEqual(self.status("readyz"), 503)
        self.assertIn(
            'node_rpc_checker_rpc_up{chain="NEAR",node="n",role="backend",transport="http"} 1',
            self.checker.metrics(),
        )

    def test_ws_failure_not_masked(self):
        fake = Fake("BASE")
        checker = Checker(
            Config("BASE", {"n": Node("node", "ws://node")}, "trusted"), fake, lambda: self.now
        )
        checker.cycle("n")
        checker.reference.fetch = lambda: (_ for _ in ()).throw(RpcError("offline"))
        self.now = 31
        fake.height += 1
        checker.cycle("n")
        self.assertEqual(checker.response("/pruning/n")[0], 200)
        fake.ws_bad = True
        checker.cycle("n")
        self.assertEqual(checker.response("/pruning/n")[0], 503)

    def test_reserved_outcome_keys_are_internal_errors(self):
        for key in ("ok", "error", "error_kind"):
            with patch.object(self.checker, "internal_error") as report:
                row = self.checker.record("n", "http/height", lambda: {key: False})
                self.assertEqual(row["error_kind"], "internal_error")
                report.assert_called_once()

    def test_expired_deep_checks_are_not_masked(self):
        self.outage()
        self.advance(31)
        with self.checker.lock:
            for row in self.checker.states["n"].values():
                if row["mode"] == "archive":
                    row["monotonic_at"] = -200
        self.assertEqual(self.status("archive"), 503)
        self.assertEqual(self.status("pruning"), 200)

    def test_reference_failure_reported_before_cached_height_expires(self):
        self.outage()
        with self.assertRaises(RpcError):
            self.checker.reference.get(refresh=True)
        self.advance(1)
        self.assertEqual(self.status("archive"), 200)
        self.assertIn(
            'node_rpc_checker_rpc_up{chain="NEAR",node="",role="trusted",transport="http"} 0',
            self.checker.metrics(),
        )

    def test_target_checks_do_not_retry_expired_reference(self):
        self.now = 31
        self.fake.height += 1
        with patch.object(
            self.checker.reference, "fetch", side_effect=AssertionError("must not fetch")
        ) as fetch:
            self.checker.cycle("n")
        fetch.assert_not_called()
        self.assertEqual(self.status("archive"), 200)

    def test_positive_stale_delta_is_diagnostic_not_a_lag_failure(self):
        self.fake.height = self.fake.reference - 100
        self.checker = Checker(
            Config("NEAR", {"n": Node("node")}, "trusted"), self.fake, lambda: self.now
        )
        self.checker.cycle("n")
        self.assertEqual(self.status("readyz"), 503)
        self.outage()
        self.advance(31)
        self.assertEqual(self.status("readyz"), 200)
        self.assertGreater(self.checker.snapshot("n")["n"]["http/height"]["delta_blocks"], 0)

    def test_reference_expiry_during_lagging_probe_is_not_target_failure(self):
        self.checker.reference.fetch = lambda: self.fake.height + 100
        self.checker.reference.get(refresh=True)
        self.now = 29
        original = self.checker.engine.height

        def slow(url):
            self.now = 31
            return original(url)

        with patch.object(self.checker.engine, "height", side_effect=slow):
            row = self.checker.record("n", "http/height", lambda: self.checker.compare("node"))
        self.assertTrue(row["ok"])
        self.assertFalse(row["reference_fresh"])
        self.assertEqual(row["delta_blocks"], 100)
