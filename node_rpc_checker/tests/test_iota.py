import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from node_rpc_checker.adapters import adapter_for
from node_rpc_checker.config import Config, Node
from node_rpc_checker.engine import Engine, parse
from node_rpc_checker.rpc import RpcClient, RpcEndpointError, RpcError
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import Rule, Spec


class IotaRpc:
    def __init__(self, chain="6364aad5"):
        self.chain = chain
        self.height = 1000000
        self.earliest = 0
        self.offset = 0
        self.calls = []

    def call(self, url, payload):
        self.calls.append(payload)
        method = payload["method"]
        if method == "iota_getChainIdentifier":
            result = self.chain
        elif method == "iota_getLatestCheckpointSequenceNumber":
            result = str(self.height)
        elif method == "iota_getCheckpoints":
            assert payload["params"] == [None, 1, False]
            result = {"data": [{"sequenceNumber": str(self.earliest)}]}
        elif method == "iota_getCheckpoint":
            result = {"sequenceNumber": str(int(payload["params"][0]) + self.offset), "digest": "d"}
        elif method == "iotax_getTotalTransactions":
            result = "0"
        else:
            raise AssertionError(method)
        return {"jsonrpc": "2.0", "id": payload["id"], "result": result}

    def subscription(self, url, subscribe, unsubscribe):
        assert subscribe["method"] == "iotax_subscribeTransaction"
        assert subscribe["params"] == [{"FromAddress": "0x" + "0" * 64}]
        assert unsubscribe["method"] == "iotax_unsubscribeTransaction"
        return {"subscription": True}


class IotaTests(unittest.TestCase):
    def test_networks_node_types_and_transports(self):
        for chain, expected in (("IOTA", "6364aad5"), ("IOTAT", "2304aa97")):
            for kind in ("auto", "prune", "archive"):
                with self.subTest(chain=chain, kind=kind):
                    rpc = IotaRpc(expected)
                    node = Node("node", "ws://node", ("indexer",), kind)
                    checker = Checker(Config(chain, {"n": node}, "trusted"), rpc)
                    checker.cycle("n")
                    self.assertEqual(checker.response("/pruning/n")[0], 200, checker.snapshot())
                    self.assertEqual(
                        checker.response("/archive/n")[0], 503 if kind == "prune" else 200
                    )
                    self.assertEqual(len(checker.spec.rules(())), 3)
                    self.assertEqual(len(checker.spec.rules(("indexer",))), 4)
                    for transport in ("http", "ws"):
                        self.assertEqual(
                            f"{transport}/pruning@archive" in checker.plans["n"], kind != "prune"
                        )

    def test_retention_and_archive(self):
        rpc = IotaRpc()
        checker = Checker(Config("IOTA", {"n": Node("node")}, "trusted"), rpc)
        for retained, status in ((863999, 503), (864000, 200), (864001, 200)):
            rpc.earliest = rpc.height - retained
            checker.cycle("n")
            self.assertEqual(checker.response("/pruning/n")[0], status)
            self.assertEqual(checker.response("/archive/n")[0], 503)
        rpc.earliest = 0
        checker.cycle("n")
        self.assertEqual(checker.response("/archive/n")[0], 200)

    def test_chain_id_and_checkpoint_identity(self):
        rpc = IotaRpc()
        spec = Spec("IOTA")
        engine = Engine(spec, rpc, adapter_for("IOTA"))
        for chain in ("6364aad5", "6364AAD5"):
            rpc.chain = chain
            engine.verify("node", spec.chain_rule)
        for chain in ("2304aa97", "0x6364aad5", "", None, 6364, "zzzzzzzz"):
            rpc.chain = chain
            with self.subTest(chain=chain), self.assertRaises(RpcError):
                engine.verify("node", spec.chain_rule)
        rule = Rule(
            "block", "archive", spec.directives["GET_BLOCK_BY_NUM"], {"expected_value": "1"}
        )
        engine.verify("node", rule)
        rpc.offset = 1
        with self.assertRaisesRegex(RpcError, "unexpected returned block height"):
            engine.verify("node", rule)

    def test_malformed_array_and_evm_hex(self):
        pd = Spec("IOTA").directives["GET_EARLIEST_BLOCK"]
        for result in ({"data": []}, {"data": [None]}, {"data": [{}]}, {}, {"data": "bad"}):
            with self.subTest(result=result), self.assertRaises(RpcError):
                parse({"result": result}, pd)
        with self.assertRaises(RpcError):
            parse({"result": "89"}, Spec("POLYGON").chain_rule.directive)

    def test_reference_and_config(self):
        rpc, trusted = IotaRpc(), IotaRpc()
        trusted.height += 3
        config = Config("IOTA", {"n": Node("node")}, "trusted", max_behind_blocks=2)
        checker = Checker(config, rpc, trusted_client=trusted)
        checker.cycle("n")
        self.assertEqual(checker.response("/readyz/n")[0], 503)
        trusted.chain = "2304aa97"
        with self.assertRaises(RpcError):
            Engine(checker.spec, trusted, adapter_for("IOTA")).reference_height("trusted")
        for chain in ("IOTA", "IOTAT"):
            with patch.dict(
                os.environ, {"CHAIN_ID": chain, "NODE_RPC_URL": "http://node"}, clear=True
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()
                os.environ["TRUSTED_RPC_URL"] = "http://trusted"
                self.assertEqual(Config.from_env().chain_id, chain)
                os.environ["REST_URL"] = "http://node:1317"
                with self.assertRaises(ValueError):
                    Config.from_env()

    def test_http_transport(self):
        rpc = IotaRpc()

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
            config = Config("IOTA", {"n": Node(url, addons=("indexer",))}, url, retries=0)
            checker = Checker(config, RpcClient(config, threading.Event()))
            checker.cycle("n")
            self.assertEqual(checker.response("/archive/n")[0], 200, checker.snapshot())
            self.assertIn('chain="IOTA"', checker.metrics())
            self.assertIn("iotax_getTotalTransactions", [call["method"] for call in rpc.calls])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_subscription_ids_and_notifications(self):
        subscribe, unsubscribe = adapter_for("IOTA").subscription_requests(Spec("IOTA").directives)
        config = Config("IOTA", {"n": Node("node")}, "trusted")
        client = RpcClient(config, threading.Event())
        for sub in (0, 42, "token", True, -1, 1.5, "", None):
            ws = MagicMock()
            ws.receive_json.side_effect = [
                {"jsonrpc": "2.0", "id": subscribe["id"], "result": sub},
                {
                    "jsonrpc": "2.0",
                    "method": subscribe["method"],
                    "params": {"subscription": sub, "result": {}},
                },
                {"jsonrpc": "2.0", "id": unsubscribe["id"], "result": True},
            ]
            with (
                self.subTest(sub=sub),
                patch("node_rpc_checker.rpc.WebSocketConnection") as connection,
            ):
                connection.return_value.__enter__.return_value = ws
                if type(sub) is int and sub >= 0 or isinstance(sub, str) and sub:
                    self.assertEqual(
                        client.subscription("ws://node", subscribe, unsubscribe),
                        {"subscription": True},
                    )
                    self.assertEqual(ws.send_json.call_args.args[0]["params"], [sub])
                else:
                    with self.assertRaises(RpcEndpointError):
                        client.subscription("ws://node", subscribe, unsubscribe)
