import copy
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .rpc import RpcError
from .spec import Spec
from .engine import Engine
from .adapters import adapter_for
from . import __version__


def payload(method, params):
    return {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}


class Checker:
    def __init__(self, config, client, clock=time.monotonic):
        self.config, self.client, self.clock = config, client, clock
        self.spec = Spec(config.chain_id)
        self.adapter = adapter_for(config.chain_id)
        self.engine = Engine(self.spec,client,self.adapter)
        self.states = {name: {} for name in config.nodes}
        self.lock = threading.Lock()
        self.plans = {}
        for name,node in config.nodes.items():
            if node.websocket_url and not self.adapter.websocket:
                raise ValueError('WebSocket is not defined for NEAR in these specs')
            rules = self.spec.rules(node.addons)
            plan = {}
            for transport,url in [('http',node.rpc_url),('ws',node.websocket_url)]:
                if not url: continue
                for rule in rules:
                    plan[transport+'/'+rule.key] = (rule.mode,lambda url=url,rule=rule:self.engine.verify(url,rule))
                plan[transport+'/height'] = ('readyz',lambda url=url:self.engine.compare(url,config.trusted))
            if node.websocket_url:
                if 'SUBSCRIBE' not in self.spec.directives:
                    raise ValueError('WS subscription directive missing')
                plan['ws/subscription'] = ('readyz',lambda url=node.websocket_url:client.subscription(url))
            self.plans[name] = plan

    def record(self, name, key, fn):
        start = self.clock()
        try:
            details = fn() or {}
            row = {'ok': True, **details}
        except Exception as exc:
            row = {'ok': False, 'error': str(exc) if isinstance(exc, RpcError) else type(exc).__name__}
        row.update(checked_at=time.time(), monotonic_at=start,
                   mode=self.plans[name][key][0],
                   latency_ms=round((self.clock() - start) * 1000))
        with self.lock:
            self.states[name][key] = row
        return row

    def cycle(self, name, include_deep=True, pool=None):
        jobs = []
        for key,(mode,fn) in self.plans[name].items():
            deep = mode != 'readyz'
            if deep and not include_deep:
                continue
            with self.lock:
                previous = self.states[name].get(key)
            if deep and previous and self.clock() - previous['monotonic_at'] < self.config.deep_interval:
                continue
            jobs.append((key,fn))
        # Independent core checks should not expire while slow siblings run.
        # Each height comparison still reads trusted before target internally.
        def execute(executor):
            futures = [executor.submit(self.record,name,key,fn) for key,fn in jobs]
            for future in futures:
                future.result()
        if pool is None:
            with ThreadPoolExecutor(max_workers=self.config.workers) as executor:
                execute(executor)
        else:
            execute(pool)

    def run(self, name, stop):
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            while not stop.is_set():
                try:
                    self.cycle(name, include_deep=False, pool=pool)
                except Exception:
                    logging.exception('checker loop failed for %s', name)
                stop.wait(self.config.poll)

    def run_deep(self, name, archive, stop):
        # Archive I/O must never delay the regular height/shard polling loop.
        for_poll = [(k,fn) for k,(mode,fn) in self.plans[name].items()
                    if mode == ('archive' if archive else 'pruning')]
        while not stop.is_set():
            for key, fn in for_poll:
                if stop.is_set():
                    return
                self.record(name,key,fn)
            stop.wait(self.config.deep_interval)

    def snapshot(self, name=None):
        with self.lock:
            states = copy.deepcopy(self.states if name is None else {name: self.states[name]})
        for checks in states.values():
            for key, row in checks.items():
                age = max(0, self.clock() - row.pop('monotonic_at'))
                row['age_seconds'] = round(age, 3)
                row['fresh'] = age <= (self.config.deep_ttl if row['mode'] != 'readyz' else self.config.ttl)
        return states

    def readiness(self, name, checks, mode):
        levels = {'readyz'}
        if mode in ('pruning','archive'): levels.add('pruning')
        if mode == 'archive': levels.add('archive')
        required = [k for k,(level,_) in self.plans[name].items() if level in levels]
        return all(checks.get(k, {}).get('ok') and checks[k].get('fresh') for k in required)

    def response(self, path):
        parts = urlsplit(path).path.strip('/').split('/')
        endpoint = parts[0]
        if endpoint == 'healthz' and len(parts) == 1:
            return 200, {'alive': True, 'version': __version__}
        if endpoint not in ('readyz', 'pruning', 'archive', 'status') or len(parts) > 2:
            return 404, {'error': 'not found'}
        if len(parts) == 2:
            if parts[1] not in self.states:
                return 404, {'error': 'unknown node'}
        states = self.snapshot(parts[1] if len(parts) == 2 else None)
        rows = {name: {'ready': self.readiness(name,checks, endpoint),
                       'readiness':{m:self.readiness(name,checks,m) for m in ('readyz','pruning','archive')}, 'checks': checks}
                for name, checks in states.items()}
        ready = all(row['ready'] for row in rows.values())
        return (200 if endpoint == 'status' or ready else 503), {
            'chain_id': self.config.chain_id, 'version': __version__, 'ready': ready, 'mode': endpoint,
            'spec_sha256': self.spec.hashes, 'nodes': rows}

    def metrics(self):
        lines = []
        def label(v):
            return v.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        for name, checks in self.snapshot().items():
            for mode in ('readyz', 'pruning', 'archive'):
                lines.append(f'node_rpc_checker_ready{{chain="{self.config.chain_id}",node="{label(name)}",mode="{mode}"}} {int(self.readiness(name,checks,mode))}')
            for key, row in checks.items():
                tags = f'chain="{self.config.chain_id}",node="{label(name)}",check="{label(key)}"'
                lines.append(f'node_rpc_checker_check_ok{{{tags}}} {int(row["ok"])}')
                lines.append(f'node_rpc_checker_check_fresh{{{tags}}} {int(row["fresh"])}')
                lines.append(f'node_rpc_checker_latency_ms{{{tags}}} {row["latency_ms"]}')
                lines.append(f'node_rpc_checker_last_attempt_timestamp{{{tags}}} {row["checked_at"]}')
            for key in ('node_height', 'trusted_height', 'delta_blocks'):
                if key in checks.get('http/height', {}):
                    lines.append(f'node_rpc_checker_{key}{{chain="{self.config.chain_id}",node="{label(name)}"}} {checks["http/height"][key]}')
        return '\n'.join(lines) + '\n'


class BoundedHTTPServer(ThreadingHTTPServer):
    """Reject overload instead of allocating unbounded handler threads."""
    max_handlers = 32

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(self.max_handlers)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(5)
        return request, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def make_server(checker, address):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlsplit(self.path).path == '/metrics':
                code, body, content_type = 200, checker.metrics().encode(), 'text/plain; version=0.0.4'
            else:
                code, data = checker.response(self.path)
                body, content_type = json.dumps(data).encode(), 'application/json'
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass
    return BoundedHTTPServer(address, Handler)
