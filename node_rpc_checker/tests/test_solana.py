import copy
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from node_rpc_checker.adapters import adapter_for
from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcClient, RpcError
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import SOLANA_GENESIS, Spec


class SolanaRpc:
    def __init__(self, chain="SOLANA"):
        self.genesis = SOLANA_GENESIS[chain]
        self.slot = 1000000
        self.version = "3.0.0"
        self.accounts = []
        self.index_error = False
        self.calls = []

    def call(self, url, payload):
        self.calls.append(payload)
        method = payload["method"]
        if method == "getGenesisHash":
            result = self.genesis
        elif method == "getVersion":
            result = {"solana-core": self.version}
        elif method == "getLatestBlockhash":
            assert payload["params"] == [{"commitment": "finalized"}]
            result = {
                "context": {"slot": self.slot},
                "value": {"blockhash": "opaque", "lastValidBlockHeight": 123},
            }
        elif method == "getTokenAccountsByOwner":
            assert payload["params"][0] == "4Qkev8aNZcqFNSRhQzwyLMFSsi94jHqE8WNVTJzTP99F"
            if self.index_error:
                return {"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32010}}
            result = {"value": self.accounts}
        else:
            raise AssertionError(method)
        return {"jsonrpc": "2.0", "id": payload["id"], "result": result}


class SolanaTests(unittest.TestCase):
    def checker(self, rpc, chain="SOLANA", kind="auto", **kwargs):
        return Checker(Config(chain, {"n": Node("node", node_type=kind)}, "trusted", **kwargs), rpc)

    def test_inheritance_and_all_verifications(self):
        for chain in SOLANA_GENESIS:
            spec = Spec(chain)
            self.assertEqual(
                {r.key for r in spec.rules(())}, {"version", "tokens-owner-indexed", "chain-id"}
            )
            self.assertFalse(spec.collections[("jsonrpc", "POST", "WS-ONLY", "")]["enabled"])
            for kind in ("auto", "prune", "archive"):
                with self.subTest(chain=chain, kind=kind):
                    checker = self.checker(SolanaRpc(chain), chain, kind)
                    checker.cycle("n")
                    self.assertEqual(checker.response("/readyz/n")[0], 200)
                    self.assertEqual(checker.response("/pruning/n")[0], 503)
                    self.assertEqual(checker.response("/archive/n")[0], 503)
                    self.assertIsNone(checker.node_type("n", checker.snapshot()["n"]))
                    self.assertEqual(
                        set(checker.plans["n"]),
                        {
                            "http/version",
                            "http/tokens-owner-indexed",
                            "http/chain-id",
                            "http/height",
                        },
                    )

    def test_warning_is_visible_but_not_readiness_blocking(self):
        rpc = SolanaRpc()
        checker = self.checker(rpc)
        rpc.index_error = True
        checker.cycle("n")
        row = checker.snapshot()["n"]["http/tokens-owner-indexed"]
        self.assertFalse(row["ok"])
        self.assertEqual(row["severity"], "Warning")
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        self.assertEqual(checker.check_history["n", "http/tokens-owner-indexed"][0], 1)
        self.assertIn('check="http/tokens-owner-indexed"', checker.metrics())
        rpc.index_error = False
        checker.cycle("n")
        self.assertTrue(checker.snapshot()["n"]["http/tokens-owner-indexed"]["ok"])
        rpc.version = ""
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 503)

    def test_wrong_network_on_target_and_reference(self):
        rpc = SolanaRpc()
        rpc.genesis = SOLANA_GENESIS["SOLANAT"]
        checker = self.checker(rpc)
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        with self.assertRaises(RpcError):
            checker.engine.reference_height("trusted")

    def test_finalized_slot_lag_and_malformed_responses(self):
        rpc, trusted = SolanaRpc(), SolanaRpc()
        trusted.slot += 2
        config = Config("SOLANA", {"n": Node("node")}, "trusted", max_behind_blocks=2)
        checker = Checker(config, rpc, trusted_client=trusted)
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 200)
        rpc.slot -= 1
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        for slot in (True, -1, None, "bad"):
            rpc.slot = slot
            with self.subTest(slot=slot), self.assertRaises(RpcError):
                checker.engine.height("node")
        rules = {r.key: r for r in checker.spec.rules(())}
        for accounts in (None, {}, "", 0):
            rpc.accounts = accounts
            with self.subTest(accounts=accounts), self.assertRaises(RpcError):
                checker.engine.verify("node", rules["tokens-owner-indexed"])
        rpc.version = {}
        with self.assertRaises(RpcError):
            checker.engine.verify("node", rules["version"])

    def test_config_requires_reference_and_rejects_disabled_transports(self):
        for chain in SOLANA_GENESIS:
            with patch.dict(
                os.environ, {"CHAIN_ID": chain, "NODE_RPC_URL": "http://node"}, clear=True
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()
                os.environ["TRUSTED_RPC_URL"] = "http://trusted"
                self.assertEqual(Config.from_env().chain_id, chain)
                for variable, url in (
                    ("REST_URL", "http://node"),
                    ("GRPC_URL", "grpc://node:9090"),
                ):
                    with patch.dict(os.environ, {variable: url}), self.assertRaises(ValueError):
                        Config.from_env()
            with self.assertRaisesRegex(ValueError, "WebSocket is not supported"):
                Checker(
                    Config(chain, {"n": Node("node", "ws://node")}, "trusted"), SolanaRpc(chain)
                )
            with self.assertRaises(ValueError):
                adapter_for(chain).subscription_requests(Spec(chain).directives)

    def test_severity_validation_and_fail_is_required(self):
        path = Path(__file__).parents[1] / "node_rpc_checker/specs/solana.json"
        original = json.loads(path.read_bytes())
        for severity in ("Fail", "invalid"):
            document = copy.deepcopy(original)
            document["proposal"]["specs"][0]["api_collections"][0]["verifications"][1]["values"][0][
                "severity"
            ] = severity
            with (
                patch.object(Path, "glob", return_value=[path]),
                patch.object(Path, "read_bytes", return_value=json.dumps(document).encode()),
            ):
                if severity == "invalid":
                    with self.assertRaisesRegex(ValueError, "severity"):
                        Spec("SOLANA")
                else:
                    rpc = SolanaRpc()
                    rpc.index_error = True
                    checker = self.checker(rpc)
                    checker.cycle("n")
                    self.assertEqual(checker.response("/readyz/n")[0], 503)

    def test_http_integration(self):
        rpc = SolanaRpc()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = json.dumps(rpc.call("node", payload)).encode()
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
            url = f"http://127.0.0.1:{server.server_port}"
            config = Config("SOLANA", {"n": Node(url)}, url, retries=0)
            checker = Checker(config, RpcClient(config, threading.Event()))
            checker.cycle("n")
            self.assertEqual(checker.response("/readyz/n")[0], 200, checker.snapshot())
            self.assertEqual(checker.engine.height(url), rpc.slot)
            rpc.index_error = True
            checker.cycle("n")
            self.assertEqual(checker.response("/readyz/n")[0], 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
