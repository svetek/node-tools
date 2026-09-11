import os
import unittest
from unittest.mock import patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.reference import TrustedReference
from node_rpc_checker.rpc import RpcError
from node_rpc_checker.service import Checker
from tests.helpers import Fake


class MetricPrivacyTests(unittest.TestCase):
    def checker(self, expose=False):
        self.urls = [
            "https://example.test/v3/secret-path-key",
            "http://example.test/rpc?token=secret-http-key",
            "ws://example.test/ws?token=secret-ws-key",
        ]
        checker = Checker(
            Config(
                "BASE",
                {"n": Node(self.urls[1], self.urls[2])},
                self.urls[0],
                expose_endpoint_urls=expose,
            ),
            Fake(),
        )
        checker.cycle("n")
        return checker

    def test_default_never_exports_url_credentials(self):
        checker = self.checker()
        for failure in (False, True):
            if failure:
                with patch.object(checker.engine, "height", side_effect=RpcError("offline")):
                    checker.cycle("n")
            metrics = checker.metrics()
            for secret in self.urls + ["secret-path-key", "secret-http-key", "secret-ws-key"]:
                self.assertNotIn(secret, metrics)
            self.assertNotIn("endpoint=", metrics)
            self.assertEqual(metrics.count("\nnode_rpc_checker_rpc_up{"), 3)
            self.assertIn('node="",role="trusted",transport="http"', metrics)
            self.assertIn('node="n",role="backend",transport="ws"', metrics)

    def test_url_exposure_requires_explicit_opt_in(self):
        metrics = self.checker(True).metrics()
        for url in self.urls:
            self.assertIn(f'endpoint="{url}"', metrics)

    def test_same_url_keeps_distinct_roles_and_nodes(self):
        checker = Checker(Config("BASE", {"a": Node("same"), "b": Node("same")}, "same"), Fake())
        checker.cycle("a")
        checker.cycle("b")
        self.assertEqual(checker.metrics().count("\nnode_rpc_checker_rpc_up{"), 3)

    def test_config_flag_and_deprecated_grace(self):
        with patch.dict(
            os.environ, {"CHAIN_ID": "BASE", "NODE_RPC_URL": "http://node"}, clear=True
        ):
            self.assertFalse(Config.from_env().expose_endpoint_urls)
            os.environ["METRICS_EXPOSE_ENDPOINT_URLS"] = "true"
            with self.assertLogs(level="WARNING") as logs:
                self.assertTrue(Config.from_env().expose_endpoint_urls)
            self.assertIn("credentials will be exposed", " ".join(logs.output))
            os.environ["METRICS_EXPOSE_ENDPOINT_URLS"] = "typo"
            with self.assertRaises(ValueError):
                Config.from_env()
            os.environ["METRICS_EXPOSE_ENDPOINT_URLS"] = "false"
            for value in ("0", "120"):
                os.environ["REFERENCE_GRACE_SECONDS"] = value
                with self.assertLogs(level="WARNING") as logs:
                    Config.from_env()
                self.assertIn("deprecated and ignored", " ".join(logs.output))
            for value in ("-1", "nan", "inf"):
                os.environ["REFERENCE_GRACE_SECONDS"] = value
                with self.assertRaises(ValueError):
                    Config.from_env()

    def test_reference_states_are_independent_of_metric_names(self):
        now = [0]
        reference = TrustedReference(lambda: 100, 30, lambda: now[0])
        self.assertFalse(reference.has_attempted_refresh())
        reference.get()
        self.assertTrue(reference.has_attempted_refresh())
        with patch.object(reference, "fetch", side_effect=RpcError("offline")):
            with self.assertRaises(RpcError):
                reference.get(refresh=True)
        self.assertTrue(reference.cache_is_fresh())
        self.assertFalse(reference.available())
        self.assertEqual(reference.metrics()["reference_cache_fresh"], 1)
        self.assertEqual(reference.metrics()["reference_up"], 0)
        checker = self.checker()
        with patch.object(
            checker.reference, "metrics", side_effect=AssertionError("diagnostics in control flow")
        ):
            checker.compare(self.urls[1])
