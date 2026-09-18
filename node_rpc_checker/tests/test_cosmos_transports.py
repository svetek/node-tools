import base64
import hashlib
import json
import os
import struct
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import grpc

from node_rpc_checker.adapters import adapter_for
from node_rpc_checker.config import Config, Node
from node_rpc_checker.cosmos_proto import MESSAGES, PREFIX, codec
from node_rpc_checker.rpc import RpcClient, RpcEndpointError, RpcError
from node_rpc_checker.service import Checker
from node_rpc_checker.spec import Spec


class CosmosTransportsTests(unittest.TestCase):
    def setUp(self):
        self.height = 30000000
        self.network = "cosmoshub-4"
        self.wrong_block = False
        self.fail = ""
        self.status_code = 200
        self.grpc_delay = 0
        self.requests = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def respond(self, data, code=200):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.headers.get("Upgrade", "").lower() == "websocket":
                    self.websocket()
                else:
                    self.respond(fixture.rest(self.path), fixture.status_code)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path.endswith("/simulate"):
                    fixture.requests.append(("simulate", payload))
                    self.respond({"code": 3 if fixture.fail != "simulate" else 2}, 400)
                else:
                    self.respond(fixture.rpc(payload))

            def websocket(self):
                accept = base64.b64encode(
                    hashlib.sha1(
                        (
                            self.headers["Sec-WebSocket-Key"]
                            + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                        ).encode()
                    ).digest()
                ).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()

                def send(data):
                    body = json.dumps(data).encode()
                    header = (
                        bytes([0x81, len(body)])
                        if len(body) < 126
                        else bytes([0x81, 126]) + struct.pack("!H", len(body))
                    )
                    self.wfile.write(header + body)
                    self.wfile.flush()

                while True:
                    head = self.rfile.read(2)
                    if not head:
                        return
                    size = head[1] & 127
                    if size == 126:
                        size = struct.unpack("!H", self.rfile.read(2))[0]
                    mask = self.rfile.read(4)
                    body = self.rfile.read(size)
                    payload = json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(body)))
                    fixture.requests.append(("ws", payload))
                    if payload["method"] == "subscribe":
                        send(
                            {
                                "jsonrpc": "2.0",
                                "id": payload["id"],
                                "result": {} if fixture.fail != "ws" else False,
                            }
                        )
                    elif payload["method"] == "unsubscribe":
                        send(
                            {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "result": {"query": "tm.event='NewBlock'", "data": {}},
                            }
                        )
                        send({"jsonrpc": "2.0", "id": payload["id"], "result": {}})
                    else:
                        send(fixture.rpc(payload))

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.grpc_server = grpc.server(ThreadPoolExecutor(max_workers=4))
        methods = {
            method: grpc.unary_unary_rpc_method_handler(
                lambda data, context, method=method: self.grpc_response(method, data, context)
            )
            for method in ("GetNodeInfo", "GetSyncing", "GetLatestBlock", "GetBlockByHeight")
        }
        self.grpc_server.add_generic_rpc_handlers(
            (grpc.method_handlers_generic_handler(PREFIX.rstrip("/"), methods),)
        )
        port = self.grpc_server.add_insecure_port("127.0.0.1:0")
        self.grpc_server.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        self.grpc_url = f"grpc://127.0.0.1:{port}"
        self.config = Config(
            "COSMOSHUB",
            {
                "n": Node(
                    self.url,
                    self.url.replace("http", "ws") + "/websocket",
                    rest_url=self.url,
                    grpc_url=self.grpc_url,
                )
            },
            self.url,
            retries=0,
        )
        self.client = RpcClient(self.config, threading.Event())

    def tearDown(self):
        self.grpc_server.stop(0).wait()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def rpc(self, payload):
        self.assertEqual(payload["method"], "status")
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "node_info": {"network": "cosmoshub-4", "other": {"tx_index": "on"}},
                "sync_info": {
                    "latest_block_height": str(self.height),
                    "earliest_block_height": "5200791",
                    "catching_up": False,
                },
            },
        }

    def rest(self, path):
        self.requests.append(("rest", path))
        if path.endswith("node_info"):
            return {"default_node_info": {"network": self.network, "other": {"tx_index": "on"}}}
        if path.endswith("syncing"):
            return {"syncing": self.fail == "syncing"}
        height = self.height if path.endswith("latest") else int(path.rsplit("/", 1)[1])
        return {
            "block_id": {"hash": "YWJj"},
            "sdk_block": {
                "header": {"height": str(height + int(self.wrong_block)), "chain_id": self.network}
            },
        }

    def grpc_response(self, method, raw, context):
        self.requests.append(("grpc", method))
        if self.grpc_delay:
            time.sleep(self.grpc_delay)
        if self.fail == "grpc":
            context.abort(grpc.StatusCode.UNAVAILABLE, "secret endpoint")
        if self.fail == "grpc_missing":
            context.abort(grpc.StatusCode.NOT_FOUND, "secret endpoint")
        if method == "GetNodeInfo":
            return MESSAGES["NodeResponse"](
                default_node_info={"network": self.network, "other": {"tx_index": "on"}}
            ).SerializeToString()
        if method == "GetSyncing":
            return MESSAGES["SyncResponse"](syncing=self.fail == "syncing").SerializeToString()
        height = (
            self.height
            if method == "GetLatestBlock"
            else MESSAGES["HeightRequest"].FromString(raw).height
        )
        return MESSAGES["BlockResponse"](
            block_id={"hash": b"abc"},
            sdk_block={
                "header": {"height": height + int(self.wrong_block), "chain_id": self.network}
            },
        ).SerializeToString()

    def test_all_transports_required_and_exported(self):
        checker = Checker(self.config, self.client)
        checker.cycle("n")
        self.assertEqual(checker.response("/archive/n")[0], 200, checker.snapshot())
        for transport in ("http", "ws", "rest", "grpc"):
            self.assertIn(transport + "/height", checker.plans["n"])
            self.assertIn(f'transport="{transport}"', checker.metrics())
        self.assertIn("rest/simulate", checker.plans["n"])
        self.assertNotIn("rest/pruning@archive", checker.plans["n"])
        self.assertNotIn("grpc/pruning@archive", checker.plans["n"])
        self.assertIn(("rest", "/cosmos/base/tendermint/v1beta1/blocks/29985600"), self.requests)
        for transport in ("ws", "grpc", "simulate", "syncing"):
            self.fail = transport
            checker.cycle("n")
            self.assertEqual(checker.response("/readyz/n")[0], 503, transport)

    def test_wrong_network_and_block_identity(self):
        checker = Checker(self.config, self.client)
        self.network = "wrong-chain"
        checker.cycle("n")
        self.assertFalse(checker.snapshot()["n"]["rest/chain-id"]["ok"])
        self.assertFalse(checker.snapshot()["n"]["grpc/chain-id"]["ok"])
        self.network = "cosmoshub-4"
        self.wrong_block = True
        checker.cycle("n")
        for transport in ("rest", "grpc"):
            self.assertIn(
                "unexpected returned block height",
                checker.snapshot()["n"][transport + "/pruning"]["error"],
            )

    def test_ws_protocol_acknowledgements(self):
        sub, unsub = adapter_for("COSMOSHUB").subscription_requests(Spec("COSMOSHUB").directives)
        self.client.subscription(self.config.nodes["n"].websocket_url, sub, unsub)
        calls = [v for k, v in self.requests if k == "ws"]
        self.assertEqual(calls, [sub, unsub])
        self.assertEqual(sub["params"], {"query": "tm.event='NewBlock'"})

    def test_transport_errors_are_sanitized(self):
        self.fail = "grpc"
        with self.assertRaises(RpcEndpointError) as error:
            self.client.grpc(self.grpc_url, PREFIX + "GetLatestBlock", {})
        self.assertNotIn("secret", str(error.exception))
        self.fail = "grpc_missing"
        with self.assertRaises(RpcError) as error:
            self.client.grpc(self.grpc_url, PREFIX + "GetBlockByHeight", {"height": "1"})
        self.assertNotIsInstance(error.exception, RpcEndpointError)
        self.status_code = 503
        with self.assertRaises(RpcEndpointError):
            self.client.rest(self.url, "/cosmos/base/tendermint/v1beta1/node_info")

    def test_grpc_deadline(self):
        self.grpc_delay = 0.3
        client = RpcClient(
            Config("COSMOSHUB", {}, self.url, timeout=0.05, retries=0), threading.Event()
        )
        with self.assertRaises(RpcEndpointError):
            client.grpc(self.grpc_url, PREFIX + "GetLatestBlock", {})


class CosmosTransportConfigTests(unittest.TestCase):
    def test_env_and_multinode(self):
        env = {
            "CHAIN_ID": "COSMOSHUB",
            "NODE_RPC_URL": "http://rpc",
            "TRUSTED_RPC_URL": "http://trusted",
            "REST_URL": "http://rest:1317",
            "GRPC_URL": "grpcs://grpc:443",
            "WEBSOCKET_URL": "ws://rpc/websocket",
        }
        with patch.dict(os.environ, env, clear=True):
            config = Config.from_env()
            self.assertEqual(config.nodes["default"].grpc_url, env["GRPC_URL"])
            self.assertEqual(config.nodes["default"].rest_url, env["REST_URL"])
        env.pop("NODE_RPC_URL")
        env["NODES_JSON"] = json.dumps(
            {
                "n": {
                    "rpc_url": "http://rpc",
                    "rest_url": "http://rest",
                    "grpc_url": "grpc://grpc:9090",
                }
            }
        )
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(Config.from_env().nodes["n"].grpc_url, "grpc://grpc:9090")
        env["CHAIN_ID"] = "BASE"
        with patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
            Config.from_env()

    def test_url_validation(self):
        for url in (
            "http://grpc",
            "grpc://user:pass@host",
            "grpc://host/path",
            "grpcs://host?token=x",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Node("http://rpc", grpc_url=url)
        with self.assertRaises(ValueError):
            Node("http://rpc", rest_url="http://rest?token=x")

    def test_wire_field_numbers(self):
        # Independent protobuf bytes: node_info(field 1), network(field 4),
        # other(field 8), tx_index(field 1). Checks against official wire tags.
        raw = b"\x0a\x13\x22\x0bcosmoshub-4\x42\x04\x0a\x02on"
        _, decode = codec(PREFIX + "GetNodeInfo", {})
        self.assertEqual(
            decode(raw), {"defaultNodeInfo": {"network": "cosmoshub-4", "other": {"txIndex": "on"}}}
        )
        data, _ = codec(PREFIX + "GetBlockByHeight", {"height": "128"})
        self.assertEqual(data, b"\x08\x80\x01")
        _, decode = codec(PREFIX + "GetSyncing", {})
        self.assertEqual(decode(b""), {"syncing": False})

    def test_optional_endpoints_and_node_type(self):
        from tests.test_cosmoshub import CosmosRpc

        for node_type in ("auto", "prune", "archive"):
            checker = Checker(
                Config(
                    "COSMOSHUB",
                    {
                        "n": Node(
                            "node",
                            node_type=node_type,
                            rest_url="http://rest",
                            grpc_url="grpc://grpc",
                        )
                    },
                    "trusted",
                ),
                CosmosRpc(),
            )
            self.assertEqual("http/pruning@archive" in checker.plans["n"], node_type != "prune")
            self.assertIn("rest/pruning", checker.plans["n"])
            self.assertIn("grpc/pruning", checker.plans["n"])
