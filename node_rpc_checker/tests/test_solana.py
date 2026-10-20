import base64
import copy
import hashlib
import json
import os
import struct
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from node_rpc_checker.adapters import adapter_for
from node_rpc_checker.config import Config, Node
from node_rpc_checker.rpc import RpcClient, RpcEndpointError, RpcError
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
        self.ws_calls = []
        self.ws_error = False

    def call(self, url, payload):
        assert not url.startswith(("ws://", "wss://")), "HTTP method sent to pubsub port"
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

    def subscription(self, url, subscribe, unsubscribe):
        self.ws_calls.append((url, subscribe, unsubscribe))
        if self.ws_error:
            raise RpcEndpointError("subscription rejected")
        return {"subscription": True}


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

    def test_advisory_metric_is_configuration_not_check_outcome(self):
        rpc = SolanaRpc()
        checker = self.checker(rpc)
        warning = 'node_rpc_checker_check_advisory{chain="SOLANA",node="n",check="http/tokens-owner-indexed"} 1'
        required = 'node_rpc_checker_check_advisory{chain="SOLANA",node="n",check="http/height"} 0'
        # Export before the first result, through failure and recovery.
        self.assertIn(warning, checker.metrics())
        self.assertIn(required, checker.metrics())
        for failed in (True, False):
            rpc.index_error = failed
            checker.cycle("n")
            metrics = checker.metrics()
            self.assertIn(warning, metrics)
            self.assertIn(required, metrics)
            self.assertIn(
                'node_rpc_checker_check_ok{chain="SOLANA",node="n",check="http/tokens-owner-indexed"} '
                + str(int(not failed)),
                metrics,
            )
            self.assertEqual(checker.response("/readyz/n")[0], 200)

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

    def test_config_requires_reference_and_rejects_rest_grpc(self):
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

    def test_ws_only_checks_subscription_and_gates_readiness(self):
        for chain in SOLANA_GENESIS:
            with self.subTest(chain=chain):
                rpc = SolanaRpc(chain)
                checker = Checker(
                    Config(chain, {"n": Node("http://node", "ws://node")}, "http://trusted"), rpc
                )
                self.assertEqual(
                    {key for key in checker.plans["n"] if key.startswith("ws/")},
                    {"ws/subscription"},
                )
                checker.cycle("n")
                self.assertEqual(checker.response("/readyz/n")[0], 200)
                ws_metric = f'node_rpc_checker_rpc_up{{chain="{chain}",node="n",role="backend",transport="ws"}}'
                self.assertIn(ws_metric + " 1\n", checker.metrics())
                self.assertNotIn(
                    f'node_rpc_checker_height_comparison_verified{{chain="{chain}",node="n",transport="ws"}}',
                    checker.metrics(),
                )
                self.assertEqual(rpc.ws_calls[-1][1]["method"], "slotSubscribe")
                self.assertEqual(rpc.ws_calls[-1][2]["method"], "slotUnsubscribe")
                rpc.ws_error = True
                checker.cycle("n")
                self.assertEqual(checker.response("/readyz/n")[0], 503)
                self.assertIn(ws_metric + " 0\n", checker.metrics())
                self.assertTrue(checker.snapshot()["n"]["http/height"]["ok"])
                rpc.ws_error = False
                checker.cycle("n")
                self.assertEqual(checker.response("/readyz/n")[0], 200)

    def test_subscription_directives_come_from_enabled_main_collection(self):
        for chain in SOLANA_GENESIS:
            spec = Spec(chain)
            subscribe, unsubscribe = adapter_for(chain).subscription_requests(spec.directives)
            self.assertEqual(subscribe["params"], [])
            self.assertEqual(subscribe["method"], "slotSubscribe")
            self.assertEqual(unsubscribe["method"], "slotUnsubscribe")
            self.assertNotEqual(subscribe["id"], unsubscribe["id"])
            # Multiple SUBSCRIBE tags must survive inheritance, not just voteSubscribe.
            methods = {d["api_name"] for d in spec.base["parse_directives"]}
            self.assertTrue({"slotSubscribe", "slotUnsubscribe", "accountSubscribe"} <= methods)
            for tag in ("SUBSCRIBE", "UNSUBSCRIBE"):
                directives = copy.deepcopy(spec.directives)
                directives.pop(tag)
                with self.assertRaises(ValueError):
                    adapter_for(chain).subscription_requests(directives)

    def test_subscription_numeric_ids_notifications_and_bad_responses(self):
        subscribe, unsubscribe = adapter_for("SOLANAT").subscription_requests(
            Spec("SOLANAT").directives
        )
        client = RpcClient(Config("SOLANAT", {}, "trusted"), threading.Event())
        for sub in (0, 42, 2**64 - 1, True, -1, 2**64, 1.5, "token", "", None):
            ws = MagicMock()
            ws.receive_json.side_effect = [
                {"jsonrpc": "2.0", "id": subscribe["id"], "result": sub},
                {
                    "jsonrpc": "2.0",
                    "method": "slotNotification",
                    "params": {"subscription": sub, "result": {"slot": 7, "parent": 6, "root": 5}},
                },
                {"jsonrpc": "2.0", "id": unsubscribe["id"], "result": True},
            ]
            with self.subTest(sub=sub), patch("node_rpc_checker.rpc.WebSocketConnection") as conn:
                conn.return_value.__enter__.return_value = ws
                if type(sub) is int and 0 <= sub < 2**64:
                    self.assertEqual(
                        client.subscription("ws://node", subscribe, unsubscribe),
                        {"subscription": True},
                    )
                    self.assertEqual(ws.send_json.call_args.args[0]["params"], [sub])
                else:
                    with self.assertRaises(RpcEndpointError):
                        client.subscription("ws://node", subscribe, unsubscribe)
        for bad in (
            {"jsonrpc": "2.0", "id": 2, "result": False},
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601}},
            {"jsonrpc": "2.0", "id": 1, "result": True},
            {"jsonrpc": "2.0", "id": 2, "result": "true"},
            {"jsonrpc": "2.0", "method": "slotNotification", "params": {"subscription": 99}},
        ):
            ws = MagicMock()
            ws.receive_json.side_effect = [{"jsonrpc": "2.0", "id": 1, "result": 42}, bad]
            with self.subTest(bad=bad), patch("node_rpc_checker.rpc.WebSocketConnection") as conn:
                conn.return_value.__enter__.return_value = ws
                with self.assertRaises(RpcEndpointError):
                    client.subscription("ws://node", subscribe, unsubscribe)

    def test_subscription_requires_valid_notification_and_unsubscribe(self):
        requests = adapter_for("SOLANAT").subscription_requests(Spec("SOLANAT").directives)
        client = RpcClient(Config("SOLANAT", {}, "trusted"), threading.Event())
        ack = {"jsonrpc": "2.0", "id": 1, "result": 42}
        notification = {
            "jsonrpc": "2.0",
            "method": "slotNotification",
            "params": {"subscription": 42, "result": {"slot": 7, "parent": 6, "root": 5}},
        }
        done = {"jsonrpc": "2.0", "id": 2, "result": True}
        for responses in (
            [ack, TimeoutError()],
            [ack, done],
            [ack, notification, {"jsonrpc": "2.0", "id": 2, "result": False}],
            [ack, notification, TimeoutError()],
        ):
            ws = MagicMock()
            ws.receive_json.side_effect = responses
            with patch("node_rpc_checker.rpc.WebSocketConnection") as conn:
                conn.return_value.__enter__.return_value = ws
                with self.assertRaises(RpcEndpointError):
                    client.subscription("ws://node", *requests)
        for key in ("slot", "root", "parent"):
            bad = copy.deepcopy(notification)
            bad["params"]["result"][key] = True
            with self.assertRaises(RpcError):
                RpcClient.validate_slot_notification(bad, 42)
        ws = MagicMock()
        ws.receive_json.side_effect = [ack, notification, notification, done]
        with patch("node_rpc_checker.rpc.WebSocketConnection") as conn:
            conn.return_value.__enter__.return_value = ws
            self.assertEqual(client.subscription("ws://node", *requests), {"subscription": True})

    def test_collection_inheritance_preserves_disabled_source(self):
        path = Path(__file__).parents[1] / "node_rpc_checker/specs/solana.json"
        original = json.loads(path.read_bytes())
        for broken in ("missing", "cycle"):
            document = copy.deepcopy(original)
            collections = document["proposal"]["specs"][0]["api_collections"]
            reference = copy.deepcopy(collections[0]["inheritance_apis"][0])
            if broken == "missing":
                reference["internal_path"] = "MISSING"
            else:
                reference["internal_path"] = ""
            collections[0]["inheritance_apis"] = [reference]
            with (
                patch.object(Path, "glob", return_value=[path]),
                patch.object(Path, "read_bytes", return_value=json.dumps(document).encode()),
                self.assertRaisesRegex(ValueError, "inheritance_apis"),
            ):
                Spec("SOLANA")
        spec = Spec("SOLANAT")
        self.assertTrue(spec.base["enabled"])
        self.assertFalse(spec.collections[("jsonrpc", "POST", "WS-ONLY", "")]["enabled"])

    def test_pubsub_server_integration(self):
        methods = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                key = self.headers["Sec-WebSocket-Key"]
                accept = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                ).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()

                def send(data):
                    raw = json.dumps(data).encode()
                    header = (
                        bytes([0x81, len(raw)])
                        if len(raw) < 126
                        else bytes([0x81, 126]) + struct.pack("!H", len(raw))
                    )
                    self.wfile.write(header + raw)
                    self.wfile.flush()

                for _ in range(2):
                    head = self.rfile.read(2)
                    length = head[1] & 127
                    if length == 126:
                        length = struct.unpack("!H", self.rfile.read(2))[0]
                    mask = self.rfile.read(4)
                    raw = self.rfile.read(length)
                    p = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(raw)))
                    methods.append(p["method"])
                    if p["method"] == "slotSubscribe" and p["params"] == []:
                        send({"jsonrpc": "2.0", "id": p["id"], "result": 0})
                        send(
                            {
                                "jsonrpc": "2.0",
                                "method": "slotNotification",
                                "params": {
                                    "subscription": 0,
                                    "result": {"slot": 1, "parent": 0, "root": 0},
                                },
                            }
                        )
                    elif p["method"] == "slotUnsubscribe" and p["params"] == [0]:
                        send({"jsonrpc": "2.0", "id": p["id"], "result": True})
                    else:
                        send({"jsonrpc": "2.0", "id": p["id"], "error": {"code": -32601}})
                        return
                self.close_connection = True

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = Config("SOLANAT", {}, "trusted", retries=0)
            client = RpcClient(config, threading.Event())
            requests = adapter_for("SOLANAT").subscription_requests(Spec("SOLANAT").directives)
            self.assertEqual(
                client.subscription(f"ws://127.0.0.1:{server.server_port}", *requests),
                {"subscription": True},
            )
            self.assertEqual(methods, ["slotSubscribe", "slotUnsubscribe"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

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
