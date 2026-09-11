import os
import threading
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from node_rpc_checker.__main__ import main
from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcClient
from node_rpc_checker.service import Checker
from tests.helpers import Fake


class TrustedTimeoutTests(unittest.TestCase):
    def load(self, **env):
        with patch.dict(
            os.environ, {"CHAIN_ID": "BASE", "NODE_RPC_URL": "http://node", **env}, clear=True
        ):
            return Config.from_env()

    def test_validation_and_independent_defaults(self):
        for value in ("0", "-1", "nan", "inf", "invalid"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.load(TRUSTED_RPC_TIMEOUT_SECONDS=value)
        with self.assertLogs(level="WARNING"):
            config = self.load(RPC_TIMEOUT_SECONDS="1")
        self.assertEqual(config.timeout, 1)
        self.assertEqual(config.trusted_timeout, 5)
        with self.assertNoLogs(level="WARNING"):
            config = self.load(TRUSTED_RPC_TIMEOUT_SECONDS="2")
        self.assertEqual(config.timeout, 3)
        self.assertEqual(config.trusted_timeout, 2)

    def test_larger_ttls_cover_nominal_budget(self):
        with self.assertNoLogs(level="WARNING"):
            self.load(TRUSTED_STATE_TTL_SECONDS="45", STATE_TTL_SECONDS="45")

    def test_role_routing_even_with_identical_urls(self):
        config = Config("BASE", {"n": Node("same", "ws://node")}, "same")
        target, trusted = Fake(), Fake()
        checker = Checker(config, target, trusted_client=trusted)
        checker.cycle("n")
        self.assertEqual(
            [payload["method"] for _, payload in trusted.calls], ["eth_chainId", "eth_blockNumber"]
        )
        self.assertTrue(target.calls)
        self.assertTrue(any(url == "same" for url, _ in target.calls))

    def test_main_constructs_separate_clients_with_shared_stop(self):
        config = Config("BASE", {"n": Node("http://node")}, "http://trusted")
        server = Mock()
        with (
            patch("node_rpc_checker.__main__.Config.from_env", return_value=config),
            patch("node_rpc_checker.__main__.Checker") as checker,
            patch("node_rpc_checker.__main__.make_server", return_value=server),
        ):
            self.assertEqual(main([]), 0)
        args, kwargs = checker.call_args
        self.assertEqual(args[1].config.timeout, 3)
        self.assertEqual(kwargs["trusted_client"].config.timeout, 5)
        self.assertIs(args[1].stop, kwargs["trusted_client"].stop)
        self.assertEqual(config.timeout, 3)

    def test_http_timeout_and_body_deadline_use_client_role(self):
        config = Config("BASE", {}, "http://same", retries=0)
        for timeout in (3, 5):
            client = RpcClient(replace(config, timeout=timeout), threading.Event())
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read1.side_effect = [b'{"jsonrpc":"2.0","id":1,"result":"0x1"}', b""]
            client.opener.open = Mock(return_value=response)
            with patch(
                "node_rpc_checker.rpc.time.monotonic", side_effect=[0, timeout - 0.1, timeout - 0.1]
            ):
                self.assertEqual(client.call("http://same", {"id": 1})["result"], "0x1")
            self.assertEqual(client.opener.open.call_args.kwargs["timeout"], timeout)
