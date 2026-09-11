import io
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from near_rpc_checker.config import Config
from near_rpc_checker.rpc import RpcClient, RpcError
from near_rpc_checker.service import Checker, make_server
from near_rpc_checker.spec import load_spec


class FakeRpc:
    def __init__(self, network='mainnet'):
        self.network = network
        self.local_height = 100000000
        self.trusted_height = 100000000
        self.shard_error = None
        self.archive = False
        self.pruning = True
        self.trusted_network = network
        self.calls = []

    def call(self, url, p):
        self.calls.append((url, p))
        method, params = p['method'], p['params']
        if method == 'status':
            return {'result': {'chain_id': self.trusted_network if url == 'trusted' else self.network,
                               'sync_info': {'syncing': False}}}
        if method == 'query':
            return {'error': {'cause': {'name': self.shard_error or 'UNKNOWN_ACCOUNT'}}}
        height = self.trusted_height if url == 'trusted' else self.local_height
        target = params.get('block_id', height)
        if target in (10000000, 42376888) and not self.archive:
            return {'error': {'cause': {'name': 'UNKNOWN_BLOCK'}}}
        if target == height-64800 and not self.pruning:
            return {'error': {'cause': {'name': 'UNKNOWN_BLOCK'}}}
        return {'result': {'header': {'height': target, 'hash': f'hash-{target}'}}}


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.rpc = FakeRpc()
        self.c = Checker(Config('mainnet', {'n': 'node'}, 'trusted'), self.rpc, lambda: self.now)

    def code(self, path='/readyz/n'):
        return self.c.response(path)[0]

    def test_initial_readiness_liveness_unknown(self):
        self.assertEqual(self.code(), 503)
        self.assertEqual(self.code('/healthz'), 200)
        self.assertEqual(self.code('/status/n'), 200)
        self.assertEqual(self.code('/archive/missing'), 404)

    def test_equal_ahead_behind_strict(self):
        for offset, code in [(0, 200), (1, 200), (-1, 503)]:
            self.rpc.local_height = self.rpc.trusted_height+offset
            self.c.cycle('n')
            self.assertEqual(self.code(), code)

    def test_all_shards_and_no_stale_success_after_failure(self):
        self.c.cycle('n')
        self.assertEqual(self.code(), 200)
        self.rpc.shard_error = 'UNAVAILABLE_SHARD'
        self.c.cycle('n')
        self.assertEqual(self.code(), 503)

    def test_archive_independent_and_pruning_required(self):
        self.c.cycle('n')
        self.assertEqual(self.code('/pruning/n'), 200)
        self.assertEqual(self.code('/archive/n'), 503)
        self.rpc.archive = True
        self.now += 61
        self.c.cycle('n')
        self.assertEqual(self.code('/archive/n'), 200)
        self.rpc.pruning = False
        self.now += 61
        self.c.cycle('n')
        self.assertEqual(self.code('/pruning/n'), 503)
        self.assertEqual(self.code('/archive/n'), 503)
        self.assertEqual(self.code('/readyz/n'), 200)
        self.assertTrue(self.c.response('/status/n')[1]['ready'])

    def test_ttl_and_deep_schedule(self):
        self.c.cycle('n')
        count = len([p for _, p in self.rpc.calls if p['method']=='block' and 'block_id' in p['params']])
        self.now += 10
        self.c.cycle('n')
        self.assertEqual(len([p for _, p in self.rpc.calls if p['method']=='block' and 'block_id' in p['params']]), count)
        self.now += 31
        self.assertEqual(self.code(), 503)

    def test_wrong_network_and_trusted_failure(self):
        self.rpc.network = 'testnet'
        self.c.cycle('n')
        self.assertEqual(self.code(), 503)
        self.rpc.network = 'mainnet'
        self.rpc.trusted_network = 'testnet'
        self.c.cycle('n')
        self.assertEqual(self.code(), 503)

    def test_testnet_inherits_pruning_and_both_archive_probes(self):
        checks, _, _ = load_spec('testnet')
        self.assertEqual(checks['chain-id']['values'][0]['expected_value'], 'testnet')
        self.assertEqual(checks['pruning']['values'][0]['latest_distance'], 64800)
        rpc = FakeRpc('testnet')
        rpc.archive = True
        c = Checker(Config('testnet', {'n': 'node'}, 'trusted'), rpc, lambda: self.now)
        c.cycle('n')
        self.assertEqual(c.response('/archive/n')[0], 200)
        blocks = {p['params'].get('block_id') for _, p in rpc.calls if p['method']=='block'}
        self.assertTrue({10000000, 42376888, 99935200}.issubset(blocks))
        self.assertEqual(sum(k.startswith('tracking-shard') for k in checks), 7)

    def test_multi_node_aggregate(self):
        self.c.states['second'] = {}
        self.c.cycle('n')
        self.assertEqual(self.code('/readyz/n'), 200)
        self.assertEqual(self.code('/readyz'), 503)
        self.assertIn('near_rpc_checker_ready', self.c.metrics())

    def test_core_loop_does_not_wait_for_deep_queries(self):
        self.c.cycle('n', include_deep=False)
        self.assertTrue(self.c.snapshot()['n']['height']['ok'])
        self.assertFalse(any(p['method']=='block' and 'block_id' in p['params'] for _, p in self.rpc.calls))
        self.assertEqual(self.code(), 200)
        self.assertEqual(self.code('/pruning/n'), 503)  # not checked yet
        self.assertEqual(self.code('/archive/n'), 503)

    def test_expired_pruning_does_not_block_core(self):
        self.rpc.archive = True
        self.c.cycle('n')
        self.now += self.c.config.deep_ttl + 1
        self.c.cycle('n', include_deep=False)
        self.assertEqual(self.code('/readyz/n'), 200)
        self.assertEqual(self.code('/pruning/n'), 503)
        self.assertEqual(self.code('/archive/n'), 503)

    def test_core_failure_blocks_every_level(self):
        self.rpc.archive = True
        self.c.cycle('n')
        self.rpc.shard_error = 'UNAVAILABLE_SHARD'
        self.c.cycle('n', include_deep=False)
        for mode in ('readyz', 'pruning', 'archive'):
            self.assertEqual(self.code('/'+mode+'/n'), 503)

    def test_separate_deep_workers(self):
        class Once:
            done = False
            def is_set(self): return self.done
            def wait(self, _seconds): self.done = True
        self.c.cycle('n', include_deep=False)
        self.c.run_deep('n', False, Once())
        self.assertEqual(self.code('/pruning/n'), 200)
        self.assertEqual(self.code('/archive/n'), 503)
        self.rpc.archive = True
        self.c.run_deep('n', True, Once())
        self.assertEqual(self.code('/archive/n'), 200)

    def test_http_server_routes(self):
        server = make_server(self.c, ('127.0.0.1', 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            with urllib.request.urlopen(base+'/healthz') as r:
                self.assertEqual(r.status, 200)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base+'/archive/n')
            self.assertEqual(error.exception.code, 503)
            self.c.cycle('n')
            with urllib.request.urlopen(base+'/pruning/n') as r:
                self.assertTrue(json.load(r)['ready'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class RpcTests(unittest.TestCase):
    def test_near_422_json_error_preserved(self):
        body = json.dumps({'jsonrpc':'2.0','id':1,'error':{'cause':{'name':'UNKNOWN_ACCOUNT'}}}).encode()
        error = urllib.error.HTTPError('http://node',422,'error',{},io.BytesIO(body))
        with patch('urllib.request.urlopen', side_effect=error):
            result = RpcClient(Config('mainnet', {}, 'trusted'), threading.Event()).call('http://node',{'id':1})
        self.assertEqual(result['error']['cause']['name'], 'UNKNOWN_ACCOUNT')

    def test_malformed_and_transport_retry(self):
        cfg = Config('mainnet', {}, 'trusted', retries=1, retry_delay=0)
        with patch('urllib.request.urlopen', side_effect=OSError('secret URL')) as mock:
            with self.assertRaises(RpcError) as exc:
                RpcClient(cfg,threading.Event()).call('http://node',{'id':1})
        self.assertEqual(mock.call_count, 2)
        self.assertNotIn('secret', str(exc.exception))


class ConfigTests(unittest.TestCase):
    def test_defaults_network_and_invalid_inputs(self):
        with patch.dict(os.environ, {'NEAR_NETWORK':'testnet','NODE_RPC_URL':'http://node:3030'}, clear=True):
            c = Config.from_env()
            self.assertEqual(c.trusted, 'https://rpc.testnet.near.org')
            self.assertEqual(c.nodes, {'default':'http://node:3030'})
        for extra in [{'NEAR_NETWORK':'other'}, {'NODES_JSON':'{}'}, {'RPC_TIMEOUT_SECONDS':'nan'}, {'HTTP_PORT':'0'}]:
            with patch.dict(os.environ, {'NODE_RPC_URL':'http://node', **extra}, clear=True):
                with self.assertRaises(ValueError):Config.from_env()


if __name__ == '__main__':
    unittest.main()
