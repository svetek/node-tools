import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcClient
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import Spec


class CosmosRpc:
    def __init__(self, network="cosmoshub-4"):
        self.network = network
        self.height = 30000000
        self.earliest = 5200791
        self.catching_up = False
        self.tx_index = "on"
        self.calls = []

    def call(self, url, payload):
        self.calls.append(payload)
        assert payload["method"] == "status", payload
        assert payload["params"] == [], payload
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "node_info": {
                    "network": self.network,
                    "other": {"tx_index": self.tx_index},
                },
                "sync_info": {
                    "latest_block_height": str(self.height),
                    "earliest_block_height": str(self.earliest),
                    "catching_up": self.catching_up,
                },
            },
        }


class CosmosHubTests(unittest.TestCase):
    def checker(self, rpc, chain="COSMOSHUB", node_type="auto"):
        return Checker(Config(chain, {"n": Node("node", node_type=node_type)}, "trusted"), rpc)

    def test_mainnet_and_testnet_inheritance(self):
        for chain, network in (("COSMOSHUB", "cosmoshub-4"), ("COSMOSHUBT", "provider")):
            with self.subTest(chain=chain):
                rpc = CosmosRpc(network)
                checker = self.checker(rpc, chain)
                checker.cycle("n")
                self.assertEqual(checker.response("/archive/n")[0], 200)
                self.assertEqual(
                    set(checker.plans["n"]),
                    {
                        "http/chain-id",
                        "http/height",
                        "http/tx-indexing",
                        "http/pruning",
                        "http/pruning@archive",
                    },
                )
                self.assertEqual(checker.spec.chain_rule.value["expected_value"], network)
        for template in ("COSMOSSDK50", "COSMOSSDK", "IBC", "TENDERMINT", "COSMOSWASM"):
            with self.assertRaisesRegex(ValueError, "disabled spec"):
                Spec(template)

    def test_pruning_boundary_and_archive_exact_height(self):
        rpc = CosmosRpc()
        checker = self.checker(rpc)
        for retained, code in ((14399, 503), (14400, 200), (14401, 200)):
            rpc.earliest = rpc.height - retained
            checker.cycle("n")
            self.assertEqual(checker.response("/pruning/n")[0], code)
            self.assertEqual(checker.response("/archive/n")[0], 503)
        rpc.earliest = 5200791
        checker.cycle("n")
        self.assertEqual(checker.response("/archive/n")[0], 200)
        rpc.earliest -= 1
        checker.cycle("n")
        self.assertEqual(checker.response("/archive/n")[0], 503)

    def test_core_failures(self):
        for field, value in (
            ("network", "wrong"),
            ("catching_up", True),
            ("catching_up", None),
            ("tx_index", "off"),
        ):
            with self.subTest(field=field, value=value):
                rpc = CosmosRpc()
                setattr(rpc, field, value)
                checker = self.checker(rpc)
                checker.cycle("n")
                self.assertEqual(checker.response("/readyz/n")[0], 503)

    def test_node_type_controls_archive_plan(self):
        for node_type in ("prune", "archive", "auto"):
            checker = self.checker(CosmosRpc(), node_type=node_type)
            self.assertEqual("http/pruning@archive" in checker.plans["n"], node_type != "prune")

    def test_config_and_unsupported_transports(self):
        for chain in ("COSMOSHUB", "COSMOSHUBT"):
            with patch.dict(
                os.environ, {"CHAIN_ID": chain, "NODE_RPC_URL": "http://node:26657"}, clear=True
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()
                os.environ["TRUSTED_RPC_URL"] = "https://reference"
                self.assertEqual(Config.from_env().chain_id, chain)
        with self.assertRaisesRegex(ValueError, "WebSocket is not supported"):
            Checker(Config("COSMOSHUB", {"n": Node("node", "ws://node")}, "trusted"), CosmosRpc())
        with self.assertRaisesRegex(ValueError, "unknown or disabled addon"):
            Spec("COSMOSHUB").rules(("rest",))

    def test_actual_http_transport(self):
        rpc = CosmosRpc()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                body = json.dumps(rpc.call("node", payload)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
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
            config = Config("COSMOSHUB", {"n": Node(url)}, url, retries=0)
            checker = Checker(config, RpcClient(config, threading.Event()))
            checker.cycle("n")
            self.assertEqual(checker.response("/archive/n")[0], 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
