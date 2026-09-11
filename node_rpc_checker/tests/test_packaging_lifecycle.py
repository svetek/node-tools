import contextlib
import io
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import tomllib
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from node_rpc_checker import __version__
from node_rpc_checker.__main__ import main
from node_rpc_checker.config import Config, Node
from node_rpc_checker.service import make_server
from node_rpc_checker.websocket import WebSocketConnection
from tools.release import main as release_main


class PackagingTests(unittest.TestCase):
    def test_version_metadata_and_wrapper_agree(self):
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root / "pyproject.toml").read_text())
        self.assertEqual(
            metadata["tool"]["setuptools"]["dynamic"]["version"]["file"], "node_rpc_checker/VERSION"
        )
        self.assertEqual((root / "node_rpc_checker/VERSION").read_text().strip(), __version__)
        self.assertEqual(
            metadata["project"]["scripts"]["node-rpc-checker"], "node_rpc_checker.__main__:main"
        )
        with (
            patch.object(sys, "argv", ["release.py", "build"]),
            patch("tools.release.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            self.assertEqual(release_main(), 0)
        command = run.call_args.args[0]
        self.assertIn(f"VERSION={__version__}", command)
        self.assertIn(f"svetekllc/node-rpc-checker:{__version__}", command)
        with (
            patch.object(sys, "argv", ["release.py", "compose", "config"]),
            patch("tools.release.subprocess.run") as run,
        ):
            with patch.dict(os.environ, {"CHECKER_VERSION": "incorrect"}):
                release_main()
        self.assertEqual(run.call_args.kwargs["env"]["CHECKER_VERSION"], __version__)

    def test_cli_version_without_configuration(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), __version__)


class HttpFailureTests(unittest.TestCase):
    def test_response_and_metrics_errors_return_sanitized_500(self):
        checker = Mock()
        checker.response.side_effect = RuntimeError("secret-token")
        checker.metrics.side_effect = RuntimeError("secret-token")
        server = make_server(checker, ("127.0.0.1", 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path in ("/status", "/metrics"):
                with self.assertLogs(level="ERROR") as logs:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(
                            f"http://127.0.0.1:{server.server_port}{path}", timeout=2
                        )
                    self.assertEqual(caught.exception.code, 500)
                    with caught.exception as response:
                        self.assertEqual(json.load(response), {"error": "internal server error"})
                self.assertNotIn("secret-token", "\n".join(logs.output))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_disconnect_never_sends_second_response(self):
        checker = Mock()
        checker.response.return_value = (200, {"alive": True})
        server = make_server(checker, ("127.0.0.1", 0))
        try:
            handler = object.__new__(server.RequestHandlerClass)
            handler.path = "/healthz"
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = Mock()
            handler.wfile.write.side_effect = BrokenPipeError()
            # Avoid a serialization failure unrelated to the disconnect.
            with patch.object(handler, "send_response") as send:
                server.RequestHandlerClass.do_GET(handler)
            send.assert_called_once()
            self.assertTrue(handler.close_connection)
        finally:
            server.server_close()

    def test_server_fallback_sanitizes_unexpected_errors(self):
        server = make_server(Mock(), ("127.0.0.1", 0))
        try:
            try:
                raise RuntimeError("secret-token")
            except RuntimeError:
                with self.assertLogs(level="ERROR") as logs:
                    server.handle_error(None, ("127.0.0.1", 1))
            self.assertNotIn("secret-token", "\n".join(logs.output))
        finally:
            server.server_close()


class ConfigMultiTests(unittest.TestCase):
    def load(self, nodes):
        with patch.dict(
            os.environ, {"CHAIN_ID": "BASE", "NODES_JSON": json.dumps(nodes)}, clear=True
        ):
            return Config.from_env()

    def test_multinode_parsing(self):
        config = self.load(
            {
                "one": {"rpc_url": "http://node", "addons": ["debug", "debug"]},
                "two": {"rpc_url": "https://other", "websocket_url": "wss://other/ws"},
            }
        )
        self.assertEqual(config.nodes["one"].addons, ("debug",))
        self.assertEqual(config.nodes["two"].websocket_url, "wss://other/ws")
        self.assertEqual(len(config.nodes), 2)

    def test_invalid_multinode_branches(self):
        variants = [
            {},
            [],
            None,
            {"bad/name": {"rpc_url": "http://node"}},
            {"n": None},
            {"n": {}},
            {"n": {"rpc_url": 1}},
            {"n": {"rpc_url": "http://node", "unknown": True}},
            {"n": {"rpc_url": "http://node", "addons": "debug"}},
            {"n": {"rpc_url": "http://node", "addons": [None]}},
            {"n": {"rpc_url": "http://node", "websocket_url": 1}},
            {"n": {"rpc_url": "http://node", "websocket_url": "http://other"}},
            {"n": {"rpc_url": "file:///secret"}},
            {"x" * 65: {"rpc_url": "http://node"}},
            {str(i): {"rpc_url": "http://node"} for i in range(65)},
        ]
        for nodes in variants:
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                self.load(nodes)
        for value in ("{", "{}"):
            with patch.dict(os.environ, {"CHAIN_ID": "BASE", "NODES_JSON": value}, clear=True):
                with self.assertRaises(ValueError):
                    Config.from_env()


class FrameTests(unittest.TestCase):
    def connection(self, frames):
        connection = WebSocketConnection("ws://node", 3)
        connection.socket = Mock()
        connection.deadline = time.monotonic() + 3
        connection._buffer = bytearray(frames)
        return connection

    def frame(self, opcode, payload=b"", final=True):
        return bytes([(0x80 if final else 0) | opcode, len(payload)]) + payload

    def test_fragmentation_with_interleaved_ping(self):
        raw = self.frame(1, b'{"result":', False) + self.frame(9, b"ping") + self.frame(0, b"123}")
        connection = self.connection(raw)
        self.assertEqual(connection.receive_json(), {"result": 123})
        self.assertEqual(connection.socket.sendall.call_count, 1)

    def test_close_and_invalid_continuations(self):
        frames = [
            self.frame(8, struct.pack("!H", 1000)),
            self.frame(0, b"{}"),
            self.frame(1, b"{", False) + self.frame(1, b"}"),
            self.frame(9, b"x", False),
        ]
        for raw in frames:
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                self.connection(raw).receive_json()

    def test_frame_and_fragment_total_size_limit(self):
        large = bytes([0x81, 127]) + struct.pack("!Q", 1048577)
        fragments = (
            bytes([0x01, 127])
            + struct.pack("!Q", 1048576)
            + b"x" * 1048576
            + bytes([0x80, 1])
            + b"x"
        )
        for raw in (large, fragments):
            with self.assertRaisesRegex(RuntimeError, "exceeds 1 MiB"):
                self.connection(raw).receive_json()

    def test_socket_close_cleanup(self):
        connection = self.connection(b"")
        connection.__exit__()
        connection.socket.close.assert_called_once()


class LifecycleTests(unittest.TestCase):
    def test_partial_thread_start_failure_cleans_up(self):
        config = Config("BASE", {"n": Node("http://node")}, "http://reference")
        server = Mock()
        threads = [Mock(), Mock(), Mock()]
        threads[1].start.side_effect = RuntimeError("secret-token")
        with (
            patch("node_rpc_checker.__main__.Config.from_env", return_value=config),
            patch("node_rpc_checker.__main__.Checker"),
            patch("node_rpc_checker.__main__.make_server", return_value=server),
            patch("node_rpc_checker.__main__.threading.Thread", side_effect=threads),
            self.assertLogs(level="ERROR"),
        ):
            self.assertEqual(main([]), 1)
        threads[0].join.assert_called_once()
        threads[1].join.assert_not_called()
        threads[2].start.assert_not_called()
        server.server_close.assert_called_once()

    def test_config_and_bind_failures(self):
        with (
            patch("node_rpc_checker.__main__.Config.from_env", side_effect=ValueError("invalid")),
            self.assertLogs(level="ERROR"),
        ):
            self.assertEqual(main([]), 2)
        config = Config("BASE", {"n": Node("http://node")}, "http://reference")
        with (
            patch("node_rpc_checker.__main__.Config.from_env", return_value=config),
            patch("node_rpc_checker.__main__.Checker"),
            patch("node_rpc_checker.__main__.make_server", side_effect=OSError("secret-token")),
            self.assertLogs(level="ERROR") as logs,
        ):
            self.assertEqual(main([]), 2)
        self.assertNotIn("secret-token", "\n".join(logs.output))

    def test_success_cleanup_and_signal_restoration(self):
        config = Config("BASE", {"n": Node("http://node")}, "http://reference")
        server = Mock()
        old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        with (
            patch("node_rpc_checker.__main__.Config.from_env", return_value=config),
            patch("node_rpc_checker.__main__.Checker") as checker,
            patch("node_rpc_checker.__main__.make_server", return_value=server),
        ):
            self.assertEqual(main([]), 0)
        server.serve_forever.assert_called_once()
        server.server_close.assert_called_once()
        self.assertEqual(checker.return_value.run.call_count, 1)
        self.assertEqual(checker.return_value.run_deep.call_count, 2)
        self.assertTrue(checker.return_value.run.call_args.args[1].is_set())
        self.assertEqual(old, {s: signal.getsignal(s) for s in old})

    def test_server_failure_cleans_up(self):
        server = Mock()
        server.serve_forever.side_effect = RuntimeError("secret-token")
        config = Config("BASE", {"n": Node("http://node")}, "http://reference")
        with (
            patch("node_rpc_checker.__main__.Config.from_env", return_value=config),
            patch("node_rpc_checker.__main__.Checker"),
            patch("node_rpc_checker.__main__.make_server", return_value=server),
            self.assertLogs(level="ERROR") as logs,
        ):
            self.assertEqual(main([]), 1)
        server.server_close.assert_called_once()
        self.assertNotIn("secret-token", "\n".join(logs.output))

    def test_real_sigterm_and_sigint(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=signum):
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    port = listener.getsockname()[1]
                env = {
                    **os.environ,
                    "CHAIN_ID": "BASE",
                    "NODE_RPC_URL": "http://127.0.0.1:9",
                    "TRUSTED_RPC_URL": "http://127.0.0.1:9",
                    "HTTP_HOST": "127.0.0.1",
                    "HTTP_PORT": str(port),
                    "RPC_TIMEOUT_SECONDS": "0.1",
                    "RPC_RETRY_COUNT": "0",
                }
                env.pop("NODES_JSON", None)
                env.pop("WEBSOCKET_URL", None)
                env.pop("ADDONS", None)
                process = subprocess.Popen(
                    [sys.executable, "-m", "node_rpc_checker"],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                try:
                    deadline = time.monotonic() + 8
                    while True:
                        try:
                            with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}/healthz", timeout=0.2
                            ):
                                break
                        except OSError:
                            if process.poll() is not None or time.monotonic() > deadline:
                                self.fail("service did not become live")
                            time.sleep(0.02)
                    process.send_signal(signum)
                    _, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, stderr.decode())
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=5)
