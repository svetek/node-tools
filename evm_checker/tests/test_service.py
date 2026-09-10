from __future__ import annotations

import json
import os
import time
import unittest
from http import HTTPStatus
from unittest.mock import Mock, patch

from evm_height_checker.config import Config, ConfigError
from evm_height_checker.rpc import RpcClient, RpcError
from evm_height_checker.service import (
    CheckerService,
    RpcEndpointError,
    SharedState,
    StatusHandler,
    evaluate_heights,
    render_multi_metrics,
    render_metrics,
)


class FakeRpcClient:
    def __init__(self, responses: dict[str, int | Exception]) -> None:
        self.responses = responses

    def get_block_number(self, url: str) -> int:
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class FakeWebSocketClient:
    def __init__(self, response: Exception | None = None) -> None:
        self.response = response
        self.checked_urls: list[str] = []

    def check_handshake(self, url: str) -> None:
        self.checked_urls.append(url)
        if self.response:
            raise self.response


class TestService(unittest.TestCase):
    def test_response_write_ignores_client_disconnect(self) -> None:
        for error in (ConnectionResetError(), BrokenPipeError()):
            with self.subTest(error=type(error).__name__):
                handler = object.__new__(StatusHandler)
                handler.path = "/readyz/base-01"
                handler.close_connection = False
                handler.send_response = Mock()
                handler.send_header = Mock()
                handler.end_headers = Mock()
                handler.wfile = Mock()
                handler.wfile.write.side_effect = error

                with patch("evm_height_checker.service.LOGGER.debug") as logger_debug:
                    handler._write_response(
                        HTTPStatus.OK, b'{"ready":true}', "application/json"
                    )

                self.assertTrue(handler.close_connection)
                logger_debug.assert_called_once()

    def test_legacy_rpc_variable_names_are_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LOCAL_RPC_URL": "http://node-rpc",
                "REMOTE_RPC_URL": "http://trusted-rpc",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ConfigError, "NODE_RPC_URL is required"):
                Config.from_env()

    def test_previous_reference_variable_name_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NODE_RPC_URL": "http://node-rpc",
                "REFERENCE_RPC_URL": "http://trusted-rpc",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ConfigError, "TRUSTED_RPC_URL is required"):
                Config.from_env()

    def test_config_accepts_multiple_named_nodes(self) -> None:
        nodes = {
            "base-01": {
                "rpc_url": "http://192.0.2.1:8545",
                "websocket_url": "ws://192.0.2.1:8546",
            },
            "base-02": {"rpc_url": "http://192.0.2.2:8545"},
        }
        with patch.dict(
            os.environ,
            {
                "NODES_JSON": json.dumps(nodes),
                "TRUSTED_RPC_URL": "https://example-rpc",
            },
            clear=True,
        ):
            config = Config.from_env()

        self.assertEqual(config.node_rpc_url, "")
        self.assertEqual(config.configured_nodes()[0].name, "base-01")
        self.assertEqual(
            config.configured_nodes()[0].websocket_url,
            "ws://192.0.2.1:8546",
        )

    def test_rpc_client_sends_user_agent(self) -> None:
        captured_headers = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"jsonrpc":"2.0","id":1,"result":"0x64"}'

        def fake_urlopen(request, timeout):
            captured_headers["User-Agent"] = request.get_header("User-agent")
            captured_headers["Accept"] = request.get_header("Accept")
            captured_headers["Content-Type"] = request.get_header("Content-type")
            return Response()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client = RpcClient(timeout_seconds=1.0, user_agent="test-agent/1.0")
            height = client.get_block_number("https://example-rpc")

        self.assertEqual(height, 100)
        self.assertEqual(captured_headers["User-Agent"], "test-agent/1.0")
        self.assertEqual(captured_headers["Accept"], "application/json")
        self.assertEqual(captured_headers["Content-Type"], "application/json")

    def test_evaluate_heights_when_node_is_ahead(self) -> None:
        result = evaluate_heights(
            node_height=200, trusted_height=199, max_behind_blocks=0
        )
        self.assertTrue(result.healthy)
        self.assertEqual(result.delta_blocks, -1)

    def test_evaluate_heights_when_node_is_too_far_behind(self) -> None:
        result = evaluate_heights(
            node_height=100, trusted_height=105, max_behind_blocks=2
        )
        self.assertFalse(result.healthy)
        self.assertEqual(result.delta_blocks, 5)

    def test_run_once_updates_state_from_rpc(self) -> None:
        config = self._config(max_behind_blocks=1)
        state = SharedState()
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.node_rpc_url: 150,
                    config.trusted_rpc_url: 151,
                }
            ),
        )

        result = service.run_once()
        snapshot = state.snapshot()

        self.assertTrue(result.healthy)
        self.assertEqual(snapshot["result"]["node_height"], 150)
        self.assertEqual(snapshot["result"]["trusted_height"], 151)
        self.assertEqual(snapshot["consecutive_failures"], 0)
        self.assertTrue(snapshot["node_rpc"]["up"])
        self.assertTrue(snapshot["trusted_rpc"]["up"])

    def test_run_once_requires_websocket_handshake_when_configured(self) -> None:
        config = self._config(max_behind_blocks=1, websocket_url="ws://local-rpc:8546")
        state = SharedState()
        websocket_client = FakeWebSocketClient()
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.node_rpc_url: 150,
                    config.trusted_rpc_url: 151,
                }
            ),
            websocket_client=websocket_client,
        )

        result = service.run_once()
        snapshot = state.snapshot()

        self.assertTrue(result.healthy)
        self.assertEqual(websocket_client.checked_urls, ["ws://local-rpc:8546"])
        self.assertTrue(snapshot["websocket"]["up"])

    def test_websocket_failure_makes_node_not_ready(self) -> None:
        config = self._config(max_behind_blocks=1, websocket_url="ws://local-rpc:8546")
        state = SharedState()
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.node_rpc_url: 150,
                    config.trusted_rpc_url: 151,
                }
            ),
            websocket_client=FakeWebSocketClient(RuntimeError("websocket unavailable")),
        )

        with self.assertRaises(RpcEndpointError):
            service.run_once()

        self.assertFalse(state.is_ready(time.time(), config.state_ttl_seconds))
        self.assertFalse(state.snapshot()["websocket"]["up"])

    def test_run_once_preserves_last_success_on_failure(self) -> None:
        config = self._config(max_behind_blocks=0)
        state = SharedState()
        state.update_success(evaluate_heights(200, 200, 0), time.time())
        state.set_endpoint_urls(config.node_rpc_url, config.trusted_rpc_url)
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.node_rpc_url: RuntimeError("node rpc failed"),
                    config.trusted_rpc_url: 200,
                }
            ),
            sleep_fn=lambda _: None,
        )

        with (
            self.assertRaises(RpcEndpointError),
            patch("evm_height_checker.service.LOGGER.error") as logger_error,
        ):
            service.run_once()

        snapshot = state.snapshot()
        logger_error.assert_called_once()
        self.assertEqual(snapshot["consecutive_failures"], 1)
        self.assertEqual(snapshot["result"]["node_height"], 200)
        self.assertIn("rpc failed for http://node-rpc", snapshot["last_error"])
        self.assertIn("node rpc failed", snapshot["last_error"])
        self.assertFalse(snapshot["node_rpc"]["up"])
        self.assertTrue(snapshot["trusted_rpc"]["up"])
        self.assertIsNotNone(snapshot["node_rpc"]["last_error_at"])

    def test_run_once_logs_rpc_failures_as_error_with_url(self) -> None:
        config = self._config(max_behind_blocks=0)
        state = SharedState()
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.node_rpc_url: RpcError(
                        "request failed for http://node-rpc: connection refused"
                    ),
                    config.trusted_rpc_url: 200,
                }
            ),
            sleep_fn=lambda _: None,
        )

        with (
            self.assertRaises(RpcEndpointError),
            patch("evm_height_checker.service.LOGGER.error") as logger_error,
            patch("evm_height_checker.service.LOGGER.exception") as logger_exception,
        ):
            service.run_once()

        logger_error.assert_called_once()
        logger_exception.assert_not_called()
        error_message = logger_error.call_args.args[0]
        error_extra = logger_error.call_args.kwargs["extra"]
        self.assertIn("rpc failed for http://node-rpc", error_message)
        self.assertEqual(error_extra["url"], "http://node-rpc")

    def test_run_once_logs_rpc_failures_as_error_with_trusted_url(self) -> None:
        config = self._config(max_behind_blocks=0)
        state = SharedState()
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.node_rpc_url: 200,
                    config.trusted_rpc_url: RpcError(
                        "request failed for http://trusted-rpc: timeout"
                    ),
                }
            ),
            sleep_fn=lambda _: None,
        )

        with (
            self.assertRaises(RpcEndpointError),
            patch("evm_height_checker.service.LOGGER.error") as logger_error,
        ):
            service.run_once()

        error_message = logger_error.call_args.args[0]
        error_extra = logger_error.call_args.kwargs["extra"]
        self.assertIn("rpc failed for http://trusted-rpc", error_message)
        self.assertEqual(error_extra["url"], "http://trusted-rpc")

    def test_ready_state_and_metrics(self) -> None:
        config = self._config(max_behind_blocks=1)
        state = SharedState()
        state.set_endpoint_urls(config.node_rpc_url, config.trusted_rpc_url)
        state.update_endpoint_success(config.node_rpc_url, time.time())
        state.update_endpoint_success(config.trusted_rpc_url, time.time())
        state.update_success(evaluate_heights(100, 101, 1), time.time())

        self.assertTrue(state.is_ready(time.time(), config.state_ttl_seconds))

        metrics = render_metrics(state.snapshot(), config, time.time())
        self.assertIn("evm_height_checker_ready 1", metrics)
        self.assertIn("evm_height_checker_trusted_height 101", metrics)
        self.assertIn('evm_height_checker_rpc_up{endpoint="http://node-rpc"} 1', metrics)
        self.assertIn(
            'evm_height_checker_rpc_up{endpoint="http://trusted-rpc"} 1', metrics
        )

    def test_ready_state_turns_false_when_stale(self) -> None:
        config = self._config(max_behind_blocks=1, state_ttl_seconds=5.0)
        state = SharedState()
        state.set_endpoint_urls(config.node_rpc_url, config.trusted_rpc_url)
        state.update_success(evaluate_heights(100, 100, 1), time.time() - 10)

        self.assertFalse(state.is_ready(time.time(), config.state_ttl_seconds))

    def test_metrics_show_failed_trusted_endpoint(self) -> None:
        config = self._config(max_behind_blocks=1)
        state = SharedState()
        state.set_endpoint_urls(config.node_rpc_url, config.trusted_rpc_url)
        state.update_endpoint_success(config.node_rpc_url, time.time())
        state.update_endpoint_failure(
            config.trusted_rpc_url,
            "rpc failed for http://trusted-rpc: timeout",
            time.time(),
        )
        state.update_success(evaluate_heights(100, 100, 1), time.time() - 1)

        metrics = render_metrics(state.snapshot(), config, time.time())
        snapshot = state.snapshot()

        self.assertIn('evm_height_checker_rpc_up{endpoint="http://node-rpc"} 1', metrics)
        self.assertIn(
            'evm_height_checker_rpc_up{endpoint="http://trusted-rpc"} 0', metrics
        )
        self.assertIn(
            'evm_height_checker_rpc_last_error_timestamp{endpoint="http://trusted-rpc"}',
            metrics,
        )
        self.assertEqual(
            snapshot["trusted_rpc"]["last_error"],
            "rpc failed for http://trusted-rpc: timeout",
        )

    def test_multi_metrics_are_labeled_by_node(self) -> None:
        config = self._config(max_behind_blocks=1)
        states = {"base-01": SharedState(), "base-02": SharedState()}
        for state in states.values():
            state.set_endpoint_urls(config.node_rpc_url, config.trusted_rpc_url)
            state.update_success(evaluate_heights(100, 101, 1), time.time())

        metrics = render_multi_metrics(states, config, time.time())

        self.assertIn('evm_height_checker_ready{node="base-01"} 1', metrics)
        self.assertIn('evm_height_checker_ready{node="base-02"} 1', metrics)
        self.assertEqual(metrics.count("# HELP evm_height_checker_ready "), 1)

    def _config(
        self,
        max_behind_blocks: int,
        state_ttl_seconds: float = 30.0,
        websocket_url: str = "",
    ) -> Config:
        return Config(
            node_rpc_url="http://node-rpc",
            trusted_rpc_url="http://trusted-rpc",
            rpc_user_agent="evm-height-checker-test/0.1",
            max_behind_blocks=max_behind_blocks,
            poll_interval_seconds=5.0,
            rpc_timeout_seconds=1.0,
            rpc_retry_count=0,
            retry_delay_seconds=0.0,
            state_ttl_seconds=state_ttl_seconds,
            http_host="127.0.0.1",
            http_port=8080,
            websocket_url=websocket_url,
        )


if __name__ == "__main__":
    unittest.main()
