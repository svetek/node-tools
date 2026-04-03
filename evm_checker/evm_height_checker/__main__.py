from __future__ import annotations

import logging
import signal
import threading

from .config import Config, ConfigError
from .logging_utils import configure_logging
from .rpc import RpcClient
from .service import CheckerService, MonitoringHTTPServer, SharedState


def main() -> int:
    configure_logging()
    logger = logging.getLogger("evm_height_checker")

    try:
        config = Config.from_env()
    except ConfigError as exc:
        logger.error(str(exc))
        return 2

    state = SharedState()
    server = MonitoringHTTPServer((config.http_host, config.http_port), config, state)
    checker = CheckerService(
        config=config,
        state=state,
        rpc_client=RpcClient(
            timeout_seconds=config.rpc_timeout_seconds,
            user_agent=config.rpc_user_agent,
        ),
    )
    stop_event = threading.Event()
    checker_thread = threading.Thread(
        target=checker.run_forever,
        args=(stop_event,),
        name="checker-loop",
        daemon=True,
    )
    checker_thread.start()

    def shutdown_handler(signum: int, _frame: object) -> None:
        logger.info("shutdown signal received", extra={"signal": signum})
        stop_event.set()
        threading.Thread(target=server.shutdown, name="http-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    logger.info(
        "service started",
        extra={"endpoint": f"http://{config.http_host}:{server.server_port}"},
    )

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop_event.set()
        server.server_close()
        checker_thread.join(timeout=max(config.rpc_timeout_seconds, config.poll_interval_seconds) + 1)
        logger.info("service stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
