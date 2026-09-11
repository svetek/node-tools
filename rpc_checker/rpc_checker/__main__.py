import logging
import signal
import threading

from .config import Config
from .rpc import RpcClient
from .service import Checker, make_server


def main():
    logging.basicConfig(level=logging.INFO)
    try:
        config = Config.from_env()
    except (ValueError, TypeError) as exc:
        logging.error('configuration: %s', exc)
        return 2
    stop = threading.Event()
    try:
        checker = Checker(config, RpcClient(config, stop))
    except (ValueError, KeyError, TypeError) as exc:
        logging.error('specification/configuration error: %s', exc)
        return 2
    server = make_server(checker, (config.host, config.port))
    threads = [threading.Thread(target=checker.run, args=(name, stop), daemon=True)
               for name in config.nodes]
    threads += [threading.Thread(target=checker.run_deep, args=(name, archive, stop), daemon=True)
                for name in config.nodes for archive in (False, True)]
    def shutdown(*_args):
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    for thread in threads:
        thread.start()
    logging.info('RPC checker started: chain=%s nodes=%s', config.chain_id, len(config.nodes))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        stop.set()
        server.server_close()
        for thread in threads:
            thread.join(timeout=config.timeout + 1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
