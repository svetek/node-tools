import os
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
        self.assertEqual(self.status("archive"), 200)

    def status(self, mode):
        return self.checker.response(f"/{mode}/n")[0]

    def outage(self):
        self.checker.reference.fetch = lambda: (_ for _ in ()).throw(RpcError("offline"))

    def advance(self, time, height=1):
        self.now = time
        self.fake.height += height
        self.checker.cycle("n", mode="readyz")

    def test_bounded_grace_and_strict_endpoint(self):
        self.outage()
        self.advance(31)
        self.assertEqual(self.status("readyz"), 503)
        self.assertEqual(self.status("pruning"), 200)
        self.assertEqual(self.status("archive"), 200)
        self.assertTrue(self.checker.response("/status/n")[1]["nodes"]["n"]["degraded"])
        self.assertIn(
            'node_rpc_checker_degraded{chain="NEAR",node="n",mode="archive"} 1',
            self.checker.metrics(),
        )
        for time in (50, 70, 90, 110, 130, 149):
            self.advance(time)
            self.assertEqual(self.status("archive"), 200)
        self.advance(150)
        self.assertEqual(self.status("archive"), 503)

    def test_no_progress_or_stale_probe_fails(self):
        self.outage()
        self.advance(31, 0)
        self.assertEqual(self.status("pruning"), 503)
        self.advance(32)
        self.assertEqual(self.status("pruning"), 200)
        self.advance(62, 0)
        self.assertEqual(self.status("pruning"), 503)

    def test_target_failure_revokes_admission_even_after_local_recovery(self):
        self.outage()
        self.advance(31)
        with patch.object(self.checker.engine, "height", side_effect=RpcError("node offline")):
            self.advance(32)
        self.advance(33)
        self.assertEqual(self.status("pruning"), 503)

    def test_shard_failure_revokes_admission(self):
        self.outage()
        self.advance(31)
        self.fake.shard = "UNAVAILABLE_SHARD"
        self.advance(32)
        self.fake.shard = "UNKNOWN_ACCOUNT"
        self.advance(33)
        self.assertEqual(self.status("archive"), 503)

    def test_regression_revokes_admission(self):
        self.outage()
        self.advance(31)
        self.advance(32, -1)
        self.advance(33)
        self.assertEqual(self.status("archive"), 503)

    def test_new_node_and_previously_behind_node_cannot_enter_grace(self):
        for behind in (False, True):
            checker = Checker(
                Config("NEAR", {"n": Node("node")}, "trusted"), self.fake, lambda: self.now
            )
            if behind:
                self.fake.height = self.fake.reference - 100
                checker.cycle("n")
            checker.reference.fetch = lambda: (_ for _ in ()).throw(RpcError("offline"))
            self.now += 31
            self.fake.height += 1
            checker.cycle("n")
            self.assertEqual(checker.response("/pruning/n")[0], 503)

    def test_fresh_reference_detecting_lag_revokes_grace(self):
        self.outage()
        self.advance(31)
        self.checker.reference.fetch = lambda: self.fake.height + 100
        self.checker.reference.get(refresh=True)
        self.advance(32)
        self.outage()
        self.advance(63)
        self.assertEqual(self.status("pruning"), 503)

    def test_ws_failure_is_not_hidden_by_reference_outage(self):
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
        self.now = 32
        fake.height += 1
        checker.cycle("n")
        self.assertEqual(checker.response("/pruning/n")[0], 503)

    def test_recovery_with_fresh_trusted_reestablishes_strict_readiness(self):
        self.outage()
        self.advance(31)
        self.checker.reference.fetch = lambda: self.fake.reference
        self.checker.reference.get(refresh=True)
        self.advance(32)
        self.assertEqual(self.status("readyz"), 200)
        self.assertFalse(self.checker.response("/status/n")[1]["nodes"]["n"]["degraded"])

    def test_expired_deep_checks_are_not_masked(self):
        self.outage()
        self.advance(31)
        with self.checker.lock:
            for row in self.checker.states["n"].values():
                if row["mode"] == "archive":
                    row["monotonic_at"] = -200
        self.assertEqual(self.status("archive"), 503)
        self.assertEqual(self.status("pruning"), 200)

    def test_disable_and_validate_grace(self):
        for value in ("-1", "nan", "inf"):
            with patch.dict(
                os.environ,
                {
                    "CHAIN_ID": "NEAR",
                    "NODE_RPC_URL": "http://node",
                    "REFERENCE_GRACE_SECONDS": value,
                },
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()
        with patch.dict(
            os.environ,
            {"CHAIN_ID": "NEAR", "NODE_RPC_URL": "http://node", "REFERENCE_GRACE_SECONDS": "0"},
            clear=True,
        ):
            config = Config.from_env()
        checker = Checker(config, self.fake, lambda: self.now)
        checker.cycle("default")
        checker.reference.fetch = lambda: (_ for _ in ()).throw(RpcError("offline"))
        self.now = 31
        self.fake.height += 1
        checker.cycle("default")
        self.assertEqual(checker.response("/pruning/default")[0], 503)
