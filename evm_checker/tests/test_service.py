from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from evm_height_checker.config import Config
from evm_height_checker.rpc import RpcClient, RpcError
from evm_height_checker.service import (
    CheckerService,
    RpcEndpointError,
    SharedState,
    evaluate_heights,
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


class TestService(unittest.TestCase):
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

    def test_evaluate_heights_when_local_is_ahead(self) -> None:
        result = evaluate_heights(local_height=200, remote_height=199, max_behind_blocks=0)
        self.assertTrue(result.healthy)
        self.assertEqual(result.delta_blocks, -1)

    def test_evaluate_heights_when_local_is_too_far_behind(self) -> None:
        result = evaluate_heights(local_height=100, remote_height=105, max_behind_blocks=2)
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
                    config.local_rpc_url: 150,
                    config.remote_rpc_url: 151,
                }
            ),
        )

        result = service.run_once()
        snapshot = state.snapshot()

        self.assertTrue(result.healthy)
        self.assertEqual(snapshot["result"]["local_height"], 150)
        self.assertEqual(snapshot["result"]["remote_height"], 151)
        self.assertEqual(snapshot["consecutive_failures"], 0)

    def test_run_once_preserves_last_success_on_failure(self) -> None:
        config = self._config(max_behind_blocks=0)
        state = SharedState()
        state.update_success(evaluate_heights(200, 200, 0), time.time())
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.local_rpc_url: RuntimeError("local rpc failed"),
                    config.remote_rpc_url: 200,
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
        self.assertEqual(snapshot["result"]["local_height"], 200)
        self.assertIn("rpc failed for http://local-rpc", snapshot["last_error"])
        self.assertIn("local rpc failed", snapshot["last_error"])

    def test_run_once_logs_rpc_failures_as_error_with_url(self) -> None:
        config = self._config(max_behind_blocks=0)
        state = SharedState()
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.local_rpc_url: RpcError("request failed for http://local-rpc: connection refused"),
                    config.remote_rpc_url: 200,
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
        self.assertIn("rpc failed for http://local-rpc", error_message)
        self.assertEqual(error_extra["url"], "http://local-rpc")

    def test_run_once_logs_rpc_failures_as_error_with_remote_url(self) -> None:
        config = self._config(max_behind_blocks=0)
        state = SharedState()
        service = CheckerService(
            config=config,
            state=state,
            rpc_client=FakeRpcClient(
                {
                    config.local_rpc_url: 200,
                    config.remote_rpc_url: RpcError("request failed for http://remote-rpc: timeout"),
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
        self.assertIn("rpc failed for http://remote-rpc", error_message)
        self.assertEqual(error_extra["url"], "http://remote-rpc")

    def test_ready_state_and_metrics(self) -> None:
        config = self._config(max_behind_blocks=1)
        state = SharedState()
        state.update_success(evaluate_heights(100, 101, 1), time.time())

        self.assertTrue(state.is_ready(time.time(), config.state_ttl_seconds))

        metrics = render_metrics(state.snapshot(), config, time.time())
        self.assertIn("evm_height_checker_ready 1", metrics)
        self.assertIn("evm_height_checker_remote_height 101", metrics)

    def test_ready_state_turns_false_when_stale(self) -> None:
        config = self._config(max_behind_blocks=1, state_ttl_seconds=5.0)
        state = SharedState()
        state.update_success(evaluate_heights(100, 100, 1), time.time() - 10)

        self.assertFalse(state.is_ready(time.time(), config.state_ttl_seconds))

    def _config(
        self,
        max_behind_blocks: int,
        state_ttl_seconds: float = 30.0,
    ) -> Config:
        return Config(
            local_rpc_url="http://local-rpc",
            remote_rpc_url="http://remote-rpc",
            rpc_user_agent="evm-height-checker-test/0.1",
            max_behind_blocks=max_behind_blocks,
            poll_interval_seconds=5.0,
            rpc_timeout_seconds=1.0,
            rpc_retry_count=0,
            retry_delay_seconds=0.0,
            state_ttl_seconds=state_ttl_seconds,
            http_host="127.0.0.1",
            http_port=8080,
        )


if __name__ == "__main__":
    unittest.main()
