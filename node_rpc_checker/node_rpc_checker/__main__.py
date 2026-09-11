import argparse
import logging
import signal
import threading
from dataclasses import replace

from . import __version__
from .config import Config
from .rpc import RpcClient
from .service import Checker, make_server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lava-spec-driven node RPC readiness service")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        config = Config.from_env()
    except (ValueError, TypeError) as exc:
        logging.error("configuration: %s", exc)
        return 2
    stop = threading.Event()
    try:
        checker = Checker(
            config,
            RpcClient(config, stop),
            trusted_client=RpcClient(replace(config, timeout=config.trusted_timeout), stop),
        )
    except (ValueError, KeyError, TypeError) as exc:
        logging.error("specification/configuration error: %s", exc)
        return 2
    try:
        server = make_server(checker, (config.host, config.port))
    except OSError as error:
        checker.internal_error("service", "listen", error)
        return 2
    threads = [
        threading.Thread(target=checker.run_mode, args=(mode, stop), daemon=True)
        for mode in ("readyz", "pruning", "archive")
    ]
    threads.append(threading.Thread(target=checker.run_reference, args=(stop,), daemon=True))

    shutdown_requested = False

    def shutdown(*_args):
        nonlocal shutdown_requested
        stop.set()
        if not shutdown_requested:
            shutdown_requested = True
            threading.Thread(target=server.shutdown, daemon=True).start()

    previous_handlers = {}
    started_threads = []
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, shutdown)
        for thread in threads:
            thread.start()
            started_threads.append(thread)
        logging.info("RPC checker started: chain=%s nodes=%s", config.chain_id, len(config.nodes))
        server.serve_forever(poll_interval=0.2)
    except Exception as error:
        checker.internal_error("service", "lifecycle", error)
        return 1
    finally:
        stop.set()
        server.server_close()
        for thread in started_threads:
            thread.join(timeout=max(config.timeout, config.trusted_timeout) + 1)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
