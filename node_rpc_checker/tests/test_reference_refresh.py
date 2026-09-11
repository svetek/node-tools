import os
import threading
import unittest
from unittest.mock import patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.engine import matches
from node_rpc_checker.rpc import RpcError
from node_rpc_checker.service import Checker
from tests.helpers import Fake
from tests.test_architecture import StopAfterWait


class RefreshTests(unittest.TestCase):
    def checker(self, **kwargs):
        self.now = [0.0]
        return Checker(
            Config("BASE", {"n": Node("node", "ws://node")}, "trusted", **kwargs),
            Fake(),
            lambda: self.now[0],
        )

    def test_readiness_stays_green_across_repeated_background_refreshes(self):
        checker = self.checker()
        checker.cycle("n", mode="readyz")
        samples = []

        def fetch():
            for _ in range(15):
                self.now[0] += 0.01
                samples.append(checker.response("/readyz/n")[0])
            return 100000000

        class Stop:
            def is_set(inner):
                return len(samples) >= 300

            def wait(inner, seconds):
                self.now[0] += seconds
                checker.cycle("n", mode="readyz")

        checker.reference.fetch = fetch
        checker.run_reference(Stop())
        self.assertEqual(set(samples), {200})
        self.assertGreater(self.now[0], checker.config.trusted_ttl)

    def test_fresh_readers_do_not_wait_and_hard_expiry_still_fails(self):
        checker = self.checker()
        checker.cycle("n", mode="readyz")
        entered, release, read = threading.Event(), threading.Event(), threading.Event()

        def fetch():
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test timeout")
            return 100000000

        checker.reference.fetch = fetch
        self.now[0] = 5
        updater = threading.Thread(target=checker.reference.get, kwargs={"refresh": True})
        reader = threading.Thread(target=lambda: (checker.compare("node"), read.set()))
        updater.start()
        try:
            self.assertTrue(entered.wait(2))
            reader.start()
            self.assertTrue(read.wait(1), "fresh reader blocked behind updater")
            self.assertEqual(checker.response("/readyz/n")[0], 200)
            self.now[0] = 30
            self.assertEqual(checker.response("/readyz/n")[0], 503)
        finally:
            release.set()
            updater.join(3)
            if reader.ident is not None:
                reader.join(3)
        self.assertFalse(updater.is_alive())
        checker.cycle("n", mode="readyz")
        self.assertEqual(checker.response("/readyz/n")[0], 200)

    def test_failed_refresh_preserves_only_unexpired_success(self):
        checker = self.checker()
        checker.cycle("n", mode="readyz")
        with patch.object(checker.reference, "fetch", side_effect=RpcError("offline")) as fetch:
            checker.run_reference(StopAfterWait(3))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        self.now[0] = 30
        self.assertEqual(checker.response("/readyz/n")[0], 503)

    def test_new_reference_cannot_extend_old_comparison_freshness(self):
        checker = self.checker()
        checker.cycle("n", mode="readyz")
        self.now[0] = 20
        checker.reference.get(refresh=True)
        self.now[0] = 30
        self.assertTrue(checker.reference.valid())
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        checker.cycle("n", mode="readyz")
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        self.assertNotIn(
            "reference_expires_at",
            checker.response("/status/n")[1]["nodes"]["n"]["checks"]["http/height"],
        )

    def test_refresh_during_slow_target_cannot_hide_reference_expiry(self):
        checker = self.checker()

        def target(url, height):
            self.now[0] = 20
            checker.reference.get(refresh=True)
            self.now[0] = 30
            return {"node_height": height}

        with patch.object(checker.engine, "compare_height", side_effect=target):
            with self.assertRaisesRegex(RpcError, "stale"):
                checker.compare("node")

    def test_reference_updater_stops_without_fetch(self):
        checker = self.checker()
        stop = threading.Event()
        stop.set()
        with patch.object(checker.reference, "fetch") as fetch:
            checker.run_reference(stop)
        fetch.assert_not_called()

    def test_background_errors_are_counted(self):
        checker = self.checker()
        with (
            patch.object(checker.reference, "fetch", side_effect=AttributeError("secret")),
            self.assertLogs(level="ERROR") as logs,
        ):
            checker.run_reference(StopAfterWait())
        self.assertNotIn("secret", "\n".join(logs.output))
        self.assertEqual(checker.internal_errors["service", "trusted_refresh"], 1)
        with (
            patch("node_rpc_checker.service.run_checks", side_effect=TypeError("secret")),
            self.assertLogs(level="ERROR"),
        ):
            checker.run_mode("readyz", StopAfterWait())
        self.assertEqual(checker.internal_errors["service", "readyz"], 1)

    def test_separate_target_timing_and_legacy_duration(self):
        checker = self.checker()

        def reference():
            self.now[0] += 2
            return 100000000

        def target(url, height):
            self.now[0] += 0.125
            return {"node_height": height}

        checker.reference.fetch = reference
        with patch.object(checker.engine, "compare_height", side_effect=target):
            row = checker.record("n", "http/height", lambda: checker.compare("node"))
        self.assertEqual(row["latency_ms"], 2125)
        self.assertEqual(row["trusted_wait_ms"], 2000)
        self.assertEqual(row["target_rpc_latency_ms"], 125)
        metrics = checker.metrics()
        for line in metrics.splitlines():
            if line.startswith("#"):
                continue
            family = line.split("{", 1)[0]
            self.assertIn(f"# HELP {family} ", metrics)
            self.assertIn(f"# TYPE {family} ", metrics)
        with self.assertLogs(level="ERROR"):
            checker.internal_error("service", "lifecycle", RuntimeError())
        self.assertIn("# TYPE node_rpc_checker_internal_errors_total counter", checker.metrics())


class RefreshConfigTests(unittest.TestCase):
    def load(self, **env):
        with patch.dict(
            os.environ, {"CHAIN_ID": "BASE", "NODE_RPC_URL": "http://node", **env}, clear=True
        ):
            return Config.from_env()

    def test_defaults_have_retry_margin(self):
        with self.assertNoLogs(level="WARNING"):
            config = self.load()
        self.assertEqual(config.trusted_ttl, 30)
        self.assertEqual(config.trusted_refresh_interval, 5)

    def test_invalid_refresh_intervals(self):
        for value in ("0", "-1", "nan", "inf", "30", "31"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load(TRUSTED_REFRESH_INTERVAL_SECONDS=value)

    def test_small_retry_budget_is_warned_not_forbidden(self):
        with self.assertLogs(level="WARNING"):
            config = self.load(TRUSTED_STATE_TTL_SECONDS="6")
        self.assertEqual(config.trusted_ttl, 6)

    def test_wildcard_is_not_truthiness(self):
        for value in (0, False, [], {}):
            self.assertTrue(matches(value, "*"))
        for value in (None, ""):
            self.assertFalse(matches(value, "*"))
