import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from node_rpc_checker.adapters import adapter_for
from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcClient, RpcEndpointError, RpcError
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import Rule, Spec
from node_rpc_checker.tezos import TezosEngine


class TezosRpc:
    def __init__(self, chain="NetXdQprcVkpaWU"):
        self.chain = chain
        self.trusted_chain = chain
        self.height = 10000000
        self.trusted_height = self.height
        self.savepoint = 0
        self.block_offset = 0
        self.calls = []

    def rest(self, url, path, method="GET"):
        self.calls.append((url, path, method))
        if method != "GET":
            raise AssertionError(method)
        if path == "/chains/main/levels/savepoint":
            return {"level": self.savepoint}
        if path == "/chains/main/blocks/head/header":
            return {
                "chain_id": self.trusted_chain if url == "trusted" else self.chain,
                "level": self.trusted_height if url == "trusted" else self.height,
                "hash": "BLockHash",
            }
        level = int(path.split("/")[-2])
        return {"level": level + self.block_offset, "hash": "BLockHash"}


class TezosTests(unittest.TestCase):
    def make_checker(self, rpc, chain="TEZOS", node_type="auto", **kwargs):
        return Checker(
            Config(chain, {"n": Node("node", node_type=node_type)}, "trusted", **kwargs), rpc
        )

    def test_networks_and_node_types(self):
        for chain, expected in (("TEZOS", "NetXdQprcVkpaWU"), ("TEZOST", "NetXsqzbfFenSTS")):
            for node_type in ("prune", "archive", "auto"):
                with self.subTest(chain=chain, node_type=node_type):
                    rpc = TezosRpc(expected)
                    checker = self.make_checker(rpc, chain, node_type)
                    checker.cycle("n")
                    self.assertEqual(checker.response("/pruning/n")[0], 200)
                    self.assertEqual(
                        checker.response("/archive/n")[0], 503 if node_type == "prune" else 200
                    )
                    self.assertEqual(
                        "http/pruning@archive" in checker.plans["n"], node_type != "prune"
                    )
                    self.assertEqual(checker.spec.chain_rule.value["expected_value"], expected)
                    self.assertEqual(len(checker.spec.rules(())), 3)

    def test_retention_boundary_and_archive(self):
        rpc = TezosRpc()
        checker = self.make_checker(rpc)
        for retained, code in ((27999, 503), (28000, 200), (28001, 200)):
            rpc.savepoint = rpc.height - retained
            checker.cycle("n")
            self.assertEqual(checker.response("/readyz/n")[0], 200)
            self.assertEqual(checker.response("/pruning/n")[0], code)
            self.assertEqual(checker.response("/archive/n")[0], 503)
        rpc.savepoint = 0
        checker.cycle("n")
        self.assertEqual(checker.response("/archive/n")[0], 200)
        self.assertEqual(checker.node_type("n", checker.snapshot()["n"]), "archive")

    def test_wrong_chain_and_lag(self):
        rpc = TezosRpc()
        checker = self.make_checker(rpc, max_behind_blocks=2)
        rpc.trusted_height += 2
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        rpc.height -= 1
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        rpc.height = rpc.trusted_height
        rpc.chain = "wrong"
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        rpc.chain = "NetXdQprcVkpaWU"
        rpc.trusted_chain = "wrong"
        with self.assertRaises(RpcError):
            checker.engine.reference_height("trusted")

    def test_separate_trusted_client_uses_rest(self):
        target, trusted = TezosRpc(), TezosRpc()
        config = Config("TEZOS", {"n": Node("node")}, "trusted")
        checker = Checker(config, target, trusted_client=trusted)
        checker.cycle("n")
        self.assertEqual(checker.response("/archive/n")[0], 200)
        self.assertTrue(trusted.calls)
        self.assertTrue(all(call[0] == "trusted" for call in trusted.calls))
        self.assertTrue(all(call[0] == "node" for call in target.calls))

    def test_malformed_results_and_block_identity(self):
        rpc = TezosRpc()
        spec = Spec("TEZOS")
        engine = TezosEngine(spec, rpc, adapter_for("TEZOS"))
        for value in (-1, "bad", None, True):
            rpc.height = value
            with self.subTest(value=value), self.assertRaises(RpcError):
                engine.height("node")
        rule = Rule(
            "block", "archive", spec.directives["GET_BLOCK_BY_NUM"], {"expected_value": "1"}
        )
        engine.verify("node", rule)
        rpc.block_offset = 1
        with self.assertRaisesRegex(RpcError, "unexpected returned block height"):
            engine.verify("node", rule)

    def test_config_requires_reference_and_rejects_other_transports(self):
        for chain in ("TEZOS", "TEZOST"):
            env = {"CHAIN_ID": chain, "NODE_RPC_URL": "http://node:8732"}
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(ValueError):
                    Config.from_env()
                os.environ["TRUSTED_RPC_URL"] = "https://reference/prefix"
                self.assertEqual(Config.from_env().chain_id, chain)
                os.environ["GRPC_URL"] = "grpc://node:9090"
                with self.assertRaises(ValueError):
                    Config.from_env()
            with self.assertRaisesRegex(ValueError, "WebSocket is not supported"):
                Checker(Config(chain, {"n": Node("node", "ws://node")}, "trusted"), TezosRpc())
            with self.assertRaisesRegex(ValueError, "must not contain a query"):
                Config(chain, {"n": Node("http://node?token=x")}, "http://trusted")

    def test_http_transport_and_malformed_body(self):
        rpc = TezosRpc()
        seen = []
        bad_body = False

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                body = json.dumps(
                    [] if bad_body else rpc.rest("node", self.path.removeprefix("/prefix"))
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/prefix"
            config = Config("TEZOS", {"n": Node(url)}, url, retries=0)
            checker = Checker(config, RpcClient(config, threading.Event()))
            checker.cycle("n")
            self.assertEqual(checker.response("/archive/n")[0], 200, checker.snapshot())
            self.assertIn("/prefix/chains/main/levels/savepoint", seen)
            self.assertIn('chain="TEZOS"', checker.metrics())
            bad_body = True
            with self.assertRaises(RpcEndpointError):
                checker.engine.height(url)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
