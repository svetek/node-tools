import os
import unittest
from unittest.mock import patch

from node_rpc_checker.adapters import adapter_for
from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcError
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import Spec
from tests.helpers import Fake


class BscTests(unittest.TestCase):
    def test_inheritance_and_node_types(self):
        for chain, expected in (("BSC", "0x38"), ("BSCT", "0x61")):
            spec = Spec(chain)
            self.assertEqual(spec.chain_rule.value["expected_value"], expected)
            self.assertEqual(
                {r.key for r in spec.rules(())},
                {"chain-id", "pruning", "pruning@archive", "trustless-rpc"},
            )
            self.assertEqual(
                {r.key for r in spec.rules(("debug", "trace", "bundler"))},
                {r.key for r in Spec("ETH1").rules(("debug", "trace", "bundler"))},
            )
            subscribe, unsubscribe = adapter_for(chain).subscription_requests(spec.directives)
            self.assertEqual(subscribe["method"], "eth_subscribe")
            self.assertEqual(subscribe["params"], ["newHeads"])
            self.assertEqual(unsubscribe["method"], "eth_unsubscribe")
            for kind in ("auto", "prune", "archive"):
                with self.subTest(chain=chain, kind=kind):
                    rpc = Fake(chain)
                    checker = Checker(
                        Config(chain, {"n": Node("node", "ws://node", node_type=kind)}, "trusted"),
                        rpc,
                    )
                    checker.cycle("n")
                    self.assertEqual(checker.response("/pruning/n")[0], 200)
                    self.assertEqual(
                        checker.response("/archive/n")[0], 503 if kind == "prune" else 200
                    )
                    self.assertEqual("http/pruning@archive" in checker.plans["n"], kind != "prune")
                    rpc.ws_bad = True
                    checker.cycle("n")
                    self.assertEqual(checker.response("/readyz/n")[0], 503)

    def test_retention_boundary_chain_and_lag(self):
        rpc = Fake("BSC")
        checker = Checker(Config("BSC", {"n": Node("node")}, "trusted", max_behind_blocks=2), rpc)
        for retained, status in ((127, 503), (128, 200), (129, 200)):
            rpc.earliest = rpc.height - retained
            checker.cycle("n")
            self.assertEqual(checker.response("/pruning/n")[0], status)
            self.assertEqual(checker.response("/archive/n")[0], 503)
        rpc.earliest = 0
        checker.cycle("n")
        self.assertEqual(checker.response("/archive/n")[0], 200)
        rpc.height = rpc.reference - 2
        checker.engine.compare("node", "trusted")
        rpc.height -= 1
        with self.assertRaises(RpcError):
            checker.engine.compare("node", "trusted")
        rpc.chain_bad = True
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        with self.assertRaises(RpcError):
            checker.engine.reference_height("trusted")

    def test_addons_are_opt_in(self):
        rpc = Fake("BSCT")
        rpc.addon_fail = True
        for addons in ((), ("debug",)):
            checker = Checker(Config("BSCT", {"n": Node("node", addons=addons)}, "trusted"), rpc)
            checker.cycle("n")
            self.assertEqual(checker.response("/readyz/n")[0], 503 if addons else 200)

    def test_requires_explicit_reference(self):
        for chain in ("BSC", "BSCT"):
            with patch.dict(
                os.environ, {"CHAIN_ID": chain, "NODE_RPC_URL": "http://node"}, clear=True
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()
                os.environ["TRUSTED_RPC_URL"] = "http://trusted"
                self.assertEqual(Config.from_env().chain_id, chain)
