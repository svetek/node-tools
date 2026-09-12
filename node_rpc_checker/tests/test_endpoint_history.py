import unittest
from unittest.mock import patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcEndpointError, RpcError
from node_rpc_checker.service import Checker
from tests.helpers import Fake


class EndpointHistoryTests(unittest.TestCase):
    def setUp(self):
        self.checker = Checker(
            Config(
                "BASE",
                {
                    "n": Node(
                        "https://example.test/rpc?token=secret", "ws://[2001:db8::1]:8546/private"
                    )
                },
                "https://trusted.test/key-secret",
            ),
            Fake(),
        )

    def record(self, at, fail=False):
        def probe():
            if fail:
                raise RpcEndpointError("offline")
            return {}

        with patch("node_rpc_checker.service.time.time", return_value=at):
            self.checker.record("n", "http/chain-id", probe)

    def test_origins_exist_before_first_check_without_secrets(self):
        metrics = self.checker.metrics()
        self.assertIn('http="https://example.test",websocket="ws://[2001:db8::1]:8546"', metrics)
        self.assertIn('address="https://trusted.test"', metrics)
        self.assertNotIn("secret", metrics)
        self.assertNotIn("/private", metrics)
        self.assertIn('check="http/chain-id",mode="readyz"} 0.0', metrics)

    def test_failures_reset_but_error_timestamp_survives_recovery(self):
        self.record(10)
        self.record(20, True)
        self.record(30, True)
        self.assertEqual(self.checker.check_history["n", "http/chain-id"], (2, 10))
        self.record(40)
        self.assertEqual(self.checker.check_history["n", "http/chain-id"], (0, 40))
        self.assertEqual(self.checker.rpc_last_errors["n", "http"], 30)
        before = dict(self.checker.check_history)
        self.checker.metrics()
        self.assertEqual(before, self.checker.check_history)

    def test_other_checks_do_not_reset_a_failed_check(self):
        self.record(10, True)
        self.checker.record("n", "ws/chain-id", lambda: {})
        self.assertEqual(self.checker.check_history["n", "http/chain-id"], (1, 0.0))

    def test_capability_failure_does_not_update_endpoint_error(self):
        def unsupported():
            raise RpcError("UNKNOWN_BLOCK")

        with patch("node_rpc_checker.service.time.time", return_value=10):
            self.checker.record("n", "http/pruning", unsupported)
        self.assertNotIn(("n", "http"), self.checker.rpc_last_errors)

    def test_trusted_failure_does_not_contaminate_backend_history(self):
        self.checker.cycle("n")
        with (
            patch.object(self.checker.reference, "fetch", side_effect=RpcError("offline")),
            patch("node_rpc_checker.reference.time.time", return_value=123),
        ):
            with self.assertRaises(RpcError):
                self.checker.reference.get(refresh=True)
        self.checker.cycle("n")
        self.assertEqual(self.checker.check_history["n", "http/height"][0], 0)
        self.assertNotIn(("n", "http"), self.checker.rpc_last_errors)
        self.assertEqual(self.checker.reference.last_error_timestamp(), 123)
        self.checker.reference.get(refresh=True)
        self.assertEqual(self.checker.reference.last_error_timestamp(), 123)
