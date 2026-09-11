import threading
import time
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.service import METRIC_DESCRIPTIONS, Checker, make_server
from tests.helpers import Fake


class CapacityTests(unittest.TestCase):
    def test_actual_plan_counts_and_warning_fields(self):
        for chain, ws, jobs in (("BASE", "", 192), ("BASE", "ws://node", 448), ("NEAR", "", 576)):
            with self.subTest(chain=chain, ws=ws), self.assertLogs(level="WARNING") as logs:
                checker = Checker(
                    Config(chain, {str(i): Node("node", ws) for i in range(64)}, "trusted"),
                    Fake(chain),
                )
            core, prune, archive = checker.capacity_estimates()
            self.assertEqual(core["jobs"], jobs)
            self.assertTrue(core["at_risk"])
            self.assertEqual(prune["jobs"], 128 if ws else 64)
            self.assertEqual(archive["jobs"], 128 if ws else 64)
            self.assertIn(f"mode=readyz jobs={jobs} workers=4", "\n".join(logs.output))
            self.assertIn("nominal_round_seconds=", "\n".join(logs.output))
            self.assertIn("interval_seconds=5 ttl_seconds=30", "\n".join(logs.output))

    def test_small_fleet_no_warning_and_no_config_mutation(self):
        config = Config("BASE", {"n": Node("node")}, "trusted")
        with self.assertNoLogs(level="WARNING"):
            checker = Checker(config, Fake())
        self.assertFalse(any(row["at_risk"] for row in checker.capacity_estimates()))
        self.assertIs(checker.config, config)
        self.assertEqual(config.workers, 4)
        self.assertEqual(config.ttl, 30)

    def test_addons_and_deep_pools_are_counted(self):
        config = Config(
            "BASE",
            {"n": Node("node", "ws://node", ("debug", "trace", "bundler"))},
            "trusted",
            deep_workers=1,
            deep_ttl=61,
        )
        with self.assertLogs(level="WARNING") as logs:
            checker = Checker(config, Fake())
        rows = checker.capacity_estimates()
        for row in rows:
            self.assertEqual(
                row["jobs"], sum(level == row["mode"] for level, _ in checker.plans["n"].values())
            )
        self.assertTrue(rows[1]["at_risk"])
        self.assertTrue(rows[2]["at_risk"])
        message = "\n".join(logs.output)
        self.assertIn("mode=pruning", message)
        self.assertIn("mode=archive", message)


class MetricHelpTests(unittest.TestCase):
    def test_metrics_http_remains_200_when_help_is_missing(self):
        checker = Checker(Config("BASE", {"n": Node("node")}, "trusted"), Fake())
        server = make_server(checker, ("127.0.0.1", 0))
        try:
            handler = object.__new__(server.RequestHandlerClass)
            handler.path = "/metrics"
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = BytesIO()
            with patch.dict(METRIC_DESCRIPTIONS, {}, clear=True), self.assertLogs(level="ERROR"):
                handler.do_GET()
            handler.send_response.assert_called_once_with(200)
            self.assertIn(b"node_rpc_checker_ready", handler.wfile.getvalue())
        finally:
            server.server_close()

    def test_all_emitted_families_have_explicit_help(self):
        checker = Checker(Config("BASE", {"n": Node("node", "ws://node")}, "trusted"), Fake())
        checker.cycle("n")
        with self.assertLogs(level="ERROR"):
            checker.internal_error("monitoring", "test", ValueError())
        text = checker.metrics()
        for line in text.splitlines():
            if line.startswith("# TYPE"):
                self.assertTrue(line.split()[2].startswith("node_rpc_checker_"))
                self.assertIn(
                    line.split()[2].removeprefix("node_rpc_checker_"), METRIC_DESCRIPTIONS
                )
        self.assertNotIn("description unavailable", text)
        self.assertNotIn("evm_height_checker_", text)
        self.assertNotIn("near_rpc_checker_", text)
        for line in text.splitlines():
            if line and not line.startswith("#"):
                self.assertTrue(line.startswith("node_rpc_checker_"))

    def test_missing_help_keeps_samples_and_reports_once(self):
        checker = Checker(Config("BASE", {"n": Node("node")}, "trusted"), Fake())
        descriptions = {
            key: value for key, value in METRIC_DESCRIPTIONS.items() if key != "max_behind_blocks"
        }
        with patch.dict(METRIC_DESCRIPTIONS, descriptions, clear=True):
            with self.assertLogs(level="ERROR"):
                first = checker.metrics()
            with self.assertNoLogs(level="ERROR"):
                second = checker.metrics()
        self.assertIn(
            "# HELP node_rpc_checker_max_behind_blocks Metric description unavailable", first
        )
        self.assertIn('node_rpc_checker_max_behind_blocks{chain="BASE"} 0', first)
        self.assertIn('node_rpc_checker_ready{chain="BASE",node="n",mode="readyz"}', first)
        self.assertEqual(checker.internal_errors["monitoring", "metric_help"], 1)
        self.assertIn('check="metric_help"} 1', second)


class SchedulerFreshnessTests(unittest.TestCase):
    def test_64_http_ws_nodes_freshness_under_sustained_latency(self):
        # Scale the timing, not the task count: 448 real BASE core plan entries.
        # At 20 ms/task, 4 workers need >=2.24 s/round, versus a 1 s state TTL;
        # 32 workers have substantial margin. Observe three TTL windows AFTER
        # all checks have run, so initial startup does not explain failures.
        for workers in (4, 32):
            with self.subTest(workers=workers):
                checker = Checker(
                    Config(
                        "BASE",
                        {str(i): Node("node", "ws://node") for i in range(64)},
                        "trusted",
                        workers=workers,
                        poll=0.1,
                        ttl=1,
                        timeout=0.02,
                    ),
                    Fake(),
                )
                stop = threading.Event()
                for plan in checker.plans.values():
                    for key, (level, fn) in list(plan.items()):

                        def delayed(fn=fn):
                            stop.wait(0.02)
                            return fn()

                        plan[key] = (level, delayed)
                errors = []

                def run():
                    try:
                        checker.run_mode("readyz", stop)
                    except Exception as exc:
                        errors.append(exc)

                thread = threading.Thread(target=run)
                thread.start()
                samples = []
                try:
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        states = checker.snapshot()
                        if sum(len(rows) for rows in states.values()) == 448:
                            break
                        stop.wait(0.025)
                    else:
                        self.fail("not all checks completed")
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        states = checker.snapshot()
                        stale = sum(
                            not row["fresh"] for rows in states.values() for row in rows.values()
                        )
                        ready = all(
                            checker.readiness(name, rows, "readyz") for name, rows in states.items()
                        )
                        samples.append((stale, ready))
                        stop.wait(0.025)
                finally:
                    stop.set()
                    thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(checker.internal_errors, {})
                if workers == 4:
                    self.assertTrue(any(stale > 0 and not ready for stale, ready in samples))
                    self.assertEqual(checker.response("/readyz")[0], 503)
                else:
                    self.assertTrue(all(stale == 0 and ready for stale, ready in samples))
                    self.assertEqual(checker.response("/readyz")[0], 200)
