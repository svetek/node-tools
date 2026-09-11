import os
import unittest
from unittest.mock import patch

from node_rpc_checker.adapters import adapter_for
from node_rpc_checker.config import Config, Node
from node_rpc_checker.engine import Engine
from node_rpc_checker.rpc import RpcError
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import Spec
from tests.helpers import Fake


class LagAllowanceTests(unittest.TestCase):
    def test_configuration_default_and_explicit_limit(self):
        for value, expected in ((None, 0), ("0", 0), ("10", 10)):
            env = {"CHAIN_ID": "BASE", "NODE_RPC_URL": "http://node"}
            if value is not None:
                env["MAX_BEHIND_BLOCKS"] = value
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(Config.from_env().max_behind_blocks, expected)

    def test_invalid_limits(self):
        for value in ("-1", "1.5", "nan", "", "true", "1e3"):
            with (
                self.subTest(value=value),
                patch.dict(
                    os.environ,
                    {"CHAIN_ID": "BASE", "NODE_RPC_URL": "http://node", "MAX_BEHIND_BLOCKS": value},
                    clear=True,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "MAX_BEHIND_BLOCKS"):
                    Config.from_env()
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                Config("BASE", {"n": Node("node")}, "trusted", max_behind_blocks=value)

    def test_inclusive_boundary_for_near_and_evm(self):
        for chain in ("BASE", "NEAR"):
            fake = Fake(chain)
            engine = Engine(Spec(chain), fake, adapter_for(chain), max_behind_blocks=10)
            for lag in (-1, 0, 9, 10):
                fake.height = fake.reference - lag
                result = engine.compare("node", "trusted")
                self.assertEqual(result["delta_blocks"], lag)
                self.assertEqual(result["max_behind_blocks"], 10)
            fake.height = fake.reference - 11
            with self.assertRaisesRegex(RpcError, "allowed=10"):
                engine.compare("node", "trusted")

    def test_all_readiness_modes_and_transports(self):
        for chain, ws in (("BASE", "ws://node"), ("NEAR", "")):
            fake = Fake(chain)
            fake.archive = True
            fake.height = fake.reference - 10
            checker = Checker(
                Config(chain, {"n": Node("node", ws)}, "trusted", max_behind_blocks=10), fake
            )
            checker.cycle("n")
            for mode in ("readyz", "pruning", "archive"):
                code, result = checker.response("/" + mode + "/n")
                self.assertEqual(code, 200)
                self.assertEqual(result["max_behind_blocks"], 10)
            self.assertIn("node_rpc_checker_max_behind_blocks", checker.metrics())
            if ws:
                self.assertEqual(checker.snapshot()["n"]["ws/height"]["delta_blocks"], 10)
            fake.height = fake.reference - 11
            checker.cycle("n", False)
            for mode in ("readyz", "pruning", "archive"):
                self.assertEqual(checker.response("/" + mode + "/n")[0], 503)

    def test_allowance_does_not_bypass_reference_freshness(self):
        now = [0]
        fake = Fake()
        checker = Checker(
            Config("BASE", {"n": Node("node")}, "trusted", max_behind_blocks=1000),
            fake,
            lambda: now[0],
        )
        checker.cycle("n", False)
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        now[0] = 6
        self.assertEqual(checker.response("/readyz/n")[0], 503)

    def test_allowance_does_not_bypass_shards(self):
        fake = Fake("NEAR")
        fake.shard = "UNAVAILABLE_SHARD"
        checker = Checker(
            Config("NEAR", {"n": Node("node")}, "trusted", max_behind_blocks=1000), fake
        )
        checker.cycle("n", False)
        self.assertEqual(checker.response("/readyz/n")[0], 503)
