import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from node_rpc_checker.adapters import Evm
from node_rpc_checker.config import Config, Node
from node_rpc_checker.reference import TrustedReference
from node_rpc_checker.rpc import RpcClient, RpcError
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import Spec, merge_collection, resolve_spec
from tests.helpers import Fake


class StopAfterWait:
    def __init__(self, cycles=1):
        self.cycles = cycles
        self.waits = []

    def is_set(self):
        return len(self.waits) >= self.cycles

    def wait(self, interval):
        self.waits.append(interval)


class ReferenceTests(unittest.TestCase):
    def test_single_flight_and_expiry(self):
        now = [0]
        fetch = MagicMock(return_value=123)
        reference = TrustedReference(fetch, 5, lambda: now[0])
        with ThreadPoolExecutor(max_workers=16) as pool:
            self.assertEqual(list(pool.map(lambda _: reference.get(), range(64))), [123] * 64)
        self.assertEqual(fetch.call_count, 1)
        now[0] = 5
        self.assertFalse(reference.cache_is_fresh())
        self.assertEqual(reference.get(), 123)
        self.assertEqual(fetch.call_count, 2)

    def test_failure_backoff_including_slow_failures(self):
        now = [0]

        def fail():
            now[0] += 20
            raise RpcError("offline")

        fetch = MagicMock(side_effect=fail)
        reference = TrustedReference(fetch, 5, lambda: now[0])
        for _ in range(32):
            with self.assertRaises(RpcError):
                reference.get()
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(reference.cache_is_fresh())
        now[0] += 5
        fetch.side_effect = None
        fetch.return_value = 10
        self.assertEqual(reference.get(), 10)

    def test_slow_success_is_not_fresh(self):
        now = [0]

        def fetch():
            now[0] += 6
            return 123

        reference = TrustedReference(fetch, 5, lambda: now[0])
        with self.assertRaisesRegex(RpcError, "expired"):
            reference.get()
        self.assertFalse(reference.cache_is_fresh())

    def test_shared_between_nodes_and_transports_and_fail_closed(self):
        now = [0]
        fake = Fake()
        nodes = {str(i): Node("http://node", "ws://node") for i in range(8)}
        checker = Checker(Config("BASE", nodes, "trusted"), fake, lambda: now[0])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: checker.cycle(n, mode="readyz"), nodes))
        self.assertEqual(sum(url == "trusted" for url, p in fake.calls), 2)
        self.assertEqual(checker.response("/readyz")[0], 200)
        now[0] = 30
        self.assertEqual(checker.response("/readyz")[0], 503)
        fake.chain_bad = True
        checker.cycle("0", mode="readyz")
        self.assertEqual(checker.response("/readyz/1")[0], 503)

    def test_reference_expiry_during_target_request(self):
        now = [0]
        checker = Checker(Config("BASE", {"n": Node("node")}, "trusted"), Fake(), lambda: now[0])

        def slow(url, height):
            now[0] = 31
            return {"node_height": height}

        with patch.object(checker.engine, "compare_height", side_effect=slow):
            with self.assertRaisesRegex(RpcError, "stale"):
                checker.compare("node")


class DiagnosticsTests(unittest.TestCase):
    def test_internal_error_stack_is_sanitized(self):
        checker = Checker(Config("BASE", {"n": Node("node")}, "trusted"), Fake())

        def broken():
            raise AttributeError("https://secret:password@private/token")

        with self.assertLogs(level="ERROR") as logs:
            row = checker.record("n", "http/height", broken)
        self.assertEqual(row["error_kind"], "internal_error")
        message = "\n".join(logs.output)
        self.assertIn("broken", message)
        self.assertIn("AttributeError", message)
        self.assertNotIn("password", message)
        self.assertNotIn("token", message)
        self.assertIn("node_rpc_checker_internal_errors_total", checker.metrics())

        def unavailable():
            raise RpcError("offline")

        with self.assertNoLogs(level="ERROR"):
            row = checker.record("n", "http/height", unavailable)
        self.assertEqual(row["error_kind"], "rpc_error")
        self.assertEqual(checker.internal_errors["n", "http/height"], 1)


class SchedulerTests(unittest.TestCase):
    def test_production_mode_routing(self):
        checker = Checker(Config("BASE", {"n": Node("node")}, "trusted"), Fake())
        for mode in ("readyz", "pruning", "archive"):
            with patch("node_rpc_checker.service.run_checks") as run:
                checker.run_mode(mode, threading.Event())
            jobs, record, report, workers, interval, stop, clock = run.call_args.args
            expected = [key for key, (level, _) in checker.plans["n"].items() if level == mode]
            self.assertEqual([key for name, key, fn in jobs], expected)
            self.assertEqual(workers, 4 if mode == "readyz" else 2)
            self.assertEqual(interval, 5 if mode == "readyz" else 60)

    def test_slow_archive_does_not_block_core(self):
        checker = Checker(Config("BASE", {"n": Node("node")}, "trusted"), Fake())
        entered, release, ready, stop = (threading.Event() for _ in range(4))

        def slow():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test timed out")
            return {}

        checker.plans["n"]["http/pruning@archive"] = ("archive", slow)
        original = checker.record

        def record(*args):
            row = original(*args)
            if checker.response("/readyz/n")[0] == 200:
                ready.set()
            return row

        threads = [
            threading.Thread(target=checker.run_mode, args=(mode, stop))
            for mode in ("archive", "readyz")
        ]
        with patch.object(checker, "record", side_effect=record):
            try:
                for thread in threads:
                    thread.start()
                self.assertTrue(entered.wait(2))
                self.assertTrue(ready.wait(2))
                self.assertEqual(checker.response("/archive/n")[0], 503)
            finally:
                stop.set()
                release.set()
                for thread in threads:
                    thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))


class SubscriptionTests(unittest.TestCase):
    def test_spec_methods_and_safe_subscription_id(self):
        directives = copy.deepcopy(Spec("BASE").directives)
        directives["SUBSCRIBE"]["api_name"] = "custom_subscribe"
        directives["UNSUBSCRIBE"].update(
            api_name="custom_unsubscribe",
            function_template='{"jsonrpc":"2.0","id":7,"method":"custom_unsubscribe","params":["%s"]}',
        )
        subscribe, unsubscribe = Evm().subscription_requests(directives)
        token = '"],"injected":true,"x":["'
        connection = MagicMock()
        connection.receive_json.side_effect = [
            {"jsonrpc": "2.0", "id": 1, "result": token},
            {"jsonrpc": "2.0", "id": 7, "result": True},
        ]
        client = RpcClient(Config("BASE", {}, "trusted"), threading.Event())
        with patch("node_rpc_checker.rpc.WebSocketConnection") as cls:
            cls.return_value.__enter__.return_value = connection
            self.assertTrue(
                client.subscription("ws://node", subscribe, unsubscribe)["subscription"]
            )
        sent = [c.args[0] for c in connection.send_json.call_args_list]
        self.assertEqual(sent[0]["method"], "custom_subscribe")
        self.assertEqual(sent[1]["method"], "custom_unsubscribe")
        self.assertEqual(sent[1]["params"], [token])
        self.assertEqual(unsubscribe["params"], ["%s"])

    def test_bad_or_missing_directives_fail_before_polling(self):
        for missing in ("SUBSCRIBE", "UNSUBSCRIBE"):
            spec = Spec("BASE")
            del spec.directives[missing]
            with patch("node_rpc_checker.service.Spec", return_value=spec):
                with self.assertRaises(ValueError):
                    Checker(Config("BASE", {"n": Node("node", "ws://node")}, "trusted"), Fake())
        directives = copy.deepcopy(Spec("BASE").directives)
        directives["UNSUBSCRIBE"]["function_template"] = '{"params":["%s","%s"]}'
        with self.assertRaises(ValueError):
            Evm().subscription_requests(directives)


class InheritanceTests(unittest.TestCase):
    def test_cycle_and_merge_are_directly_testable(self):
        with self.assertRaisesRegex(ValueError, "cyclic"):
            resolve_spec({"A": {"enabled": True, "imports": ["A"], "api_collections": []}}, "A")
        values = {}
        parent = {
            "verifications": [
                {"name": "chain-id", "values": [1], "parse_directive": {"api_name": "method"}}
            ]
        }
        merge_collection(values, "key", parent)
        merge_collection(values, "key", {"verifications": [{"name": "chain-id", "values": [2]}]})
        self.assertEqual(values["key"]["verifications"][0]["values"], [2])
        self.assertEqual(
            values["key"]["verifications"][0]["parse_directive"], {"api_name": "method"}
        )
        self.assertEqual(parent["verifications"][0]["values"], [1])
