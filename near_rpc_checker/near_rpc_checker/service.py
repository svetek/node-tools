import copy
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .rpc import RpcError, header_of, result_of
from .spec import load_spec, SOURCE


def payload(method, params):
    return {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}


class Checker:
    def __init__(self, config, client, clock=time.monotonic):
        self.config, self.client, self.clock = config, client, clock
        self.verifications, self.directives, self.spec_hash = load_spec(config.network)
        self.states = {name: {} for name in config.nodes}
        self.lock = threading.Lock()

    def record(self, name, key, fn):
        start = self.clock()
        try:
            details = fn() or {}
            row = {'ok': True, **details}
        except Exception as exc:
            row = {'ok': False, 'error': str(exc) if isinstance(exc, RpcError) else type(exc).__name__}
        row.update(checked_at=time.time(), monotonic_at=start,
                   latency_ms=round((self.clock() - start) * 1000))
        with self.lock:
            self.states[name][key] = row
        return row

    def height(self, name):
        url = self.config.nodes[name]
        # Read reference before target to avoid penalizing the target for measurement ordering.
        trusted_status = result_of(self.client.call(self.config.trusted, payload('status', [])))
        if trusted_status.get('chain_id') != self.config.network or trusted_status.get('sync_info', {}).get('syncing') is not False:
            raise RpcError('trusted node has wrong chain or is syncing')
        template = json.loads(self.directives['GET_BLOCKNUM']['function_template'])
        trusted = header_of(self.client.call(self.config.trusted, template))['height']
        local = header_of(self.client.call(url, template))['height']
        if local < trusted:
            raise RpcError(f'node behind: node={local}, trusted={trusted}, lag={trusted-local}')
        return {'node_height': local, 'trusted_height': trusted, 'delta_blocks': trusted-local}

    def verify(self, name, verification, head=None):
        url = self.config.nodes[name]
        pd = verification['parse_directive']
        value = verification['values'][0]
        if pd['function_tag'] == 'GET_BLOCK_BY_NUM':
            target = head - value['latest_distance']
            if target < 0:
                raise RpcError('chain height below pruning distance')
            template = self.directives['GET_BLOCK_BY_NUM']['function_template'] % target
            header_of(self.client.call(url, json.loads(template)), target)
            return {'block_height': target}
        response = self.client.call(url, json.loads(pd['function_template']))
        if verification['name'].startswith('tracking-shard-'):
            error = response.get('error', {})
            cause = error.get('cause', {}).get('name') if isinstance(error, dict) else None
            if cause == 'UNKNOWN_ACCOUNT':
                return {'response': cause}
            result = response.get('result')
            if isinstance(result, dict) and isinstance(result.get('amount'), str) and result['amount'].isdigit():
                return {'response': 'account-state'}
            raise RpcError(str(cause or 'invalid account response'))
        if verification['name'] == 'chain-id':
            status = result_of(response)
            if status.get('chain_id') != value['expected_value']:
                raise RpcError('wrong chain-id')
            if status.get('sync_info', {}).get('syncing') is not False:
                raise RpcError('node is syncing or sync status missing')
            return {'chain_id': status['chain_id']}
        expected = int(value['expected_value'])
        header_of(response, expected)
        return {'block_height': expected}

    def cycle(self, name, include_deep=True):
        url = self.config.nodes[name]
        for key, v in self.verifications.items():
            deep = key.startswith('pruning')
            if deep and not include_deep:
                continue
            with self.lock:
                previous = self.states[name].get(key)
            if deep and previous and self.clock() - previous['monotonic_at'] < self.config.deep_interval:
                continue
            def run(v=v):
                head = None
                if v['parse_directive']['function_tag'] == 'GET_BLOCK_BY_NUM':
                    head = header_of(self.client.call(url, json.loads(self.directives['GET_BLOCKNUM']['function_template'])))['height']
                return self.verify(name, v, head)
            self.record(name, key, run)
        self.record(name, 'height', lambda: self.height(name))

    def run(self, name, stop):
        while not stop.is_set():
            try:
                self.cycle(name, include_deep=False)
            except Exception:
                logging.exception('checker loop failed for %s', name)
            stop.wait(self.config.poll)

    def run_deep(self, name, archive, stop):
        # Archive I/O must never delay the regular height/shard polling loop.
        for_poll = [(k, v) for k, v in self.verifications.items()
                    if k.startswith('pruning') and
                    any(x.get('extension') == 'archive' for x in v['values']) == archive]
        while not stop.is_set():
            for key, v in for_poll:
                if stop.is_set():
                    return
                def run(v=v):
                    head = None
                    if not archive:
                        head = header_of(self.client.call(self.config.nodes[name],
                            json.loads(self.directives['GET_BLOCKNUM']['function_template'])))['height']
                    return self.verify(name, v, head)
                self.record(name, key, run)
            stop.wait(self.config.deep_interval)

    def snapshot(self):
        with self.lock:
            states = copy.deepcopy(self.states)
        for checks in states.values():
            for key, row in checks.items():
                age = max(0, self.clock() - row.pop('monotonic_at'))
                row['age_seconds'] = round(age, 3)
                row['fresh'] = age <= (self.config.deep_ttl if key.startswith('pruning') else self.config.ttl)
        return states

    def readiness(self, checks, mode):
        required = ['height']
        for key, v in self.verifications.items():
            archive = any(x.get('extension') == 'archive' for x in v['values'])
            if archive and mode != 'archive':
                continue
            if key == 'pruning' and mode not in ('pruning', 'archive'):
                continue
            required.append(key)
        return all(checks.get(k, {}).get('ok') and checks[k].get('fresh') for k in required)

    def response(self, path):
        parts = urlsplit(path).path.strip('/').split('/')
        endpoint = parts[0]
        if endpoint == 'healthz' and len(parts) == 1:
            return 200, {'alive': True}
        if endpoint not in ('readyz', 'pruning', 'archive', 'status') or len(parts) > 2:
            return 404, {'error': 'not found'}
        states = self.snapshot()
        if len(parts) == 2:
            if parts[1] not in states:
                return 404, {'error': 'unknown node'}
            states = {parts[1]: states[parts[1]]}
        rows = {name: {'ready': self.readiness(checks, endpoint), 'checks': checks}
                for name, checks in states.items()}
        ready = all(row['ready'] for row in rows.values())
        return (200 if endpoint == 'status' or ready else 503), {
            'network': self.config.network, 'ready': ready, 'mode': endpoint,
            'spec_sha256': self.spec_hash, 'spec_source': SOURCE, 'nodes': rows}

    def metrics(self):
        lines = []
        def label(v):
            return v.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        for name, checks in self.snapshot().items():
            for mode in ('readyz', 'pruning', 'archive'):
                lines.append(f'near_rpc_checker_ready{{node="{label(name)}",mode="{mode}"}} {int(self.readiness(checks,mode))}')
            for key, row in checks.items():
                tags = f'node="{label(name)}",check="{label(key)}"'
                lines.append(f'near_rpc_checker_check_ok{{{tags}}} {int(row["ok"])}')
                lines.append(f'near_rpc_checker_check_fresh{{{tags}}} {int(row["fresh"])}')
                lines.append(f'near_rpc_checker_latency_ms{{{tags}}} {row["latency_ms"]}')
                lines.append(f'near_rpc_checker_last_attempt_timestamp{{{tags}}} {row["checked_at"]}')
            for key in ('node_height', 'trusted_height', 'delta_blocks'):
                if key in checks.get('height', {}):
                    lines.append(f'near_rpc_checker_{key}{{node="{label(name)}"}} {checks["height"][key]}')
        return '\n'.join(lines) + '\n'


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
    return ThreadingHTTPServer(address, Handler)
