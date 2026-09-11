import base64
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from rpc_checker.adapters import adapter_for
from rpc_checker import __version__
from rpc_checker.config import Config, Node
from rpc_checker.engine import Engine, parse
from rpc_checker.rpc import RpcClient, RpcError
from rpc_checker.service import Checker, make_server
from rpc_checker.spec import Spec, validate_parser


class Fake:
    def __init__(self,chain='BASE'):
        self.chain=chain
        self.height=100000000
        self.reference=100000000
        self.earliest=0
        self.archive=False
        self.shard='UNKNOWN_ACCOUNT'
        self.syncing=False
        self.chain_bad=False
        self.addon_fail=False
        self.ws_bad=False
        self.calls=[]
    def subscription(self,url):
        if self.ws_bad:raise RpcError('WS failed')
        return {'subscription':True}
    def call(self,url,p):
        self.calls.append((url,p))
        method=p['method'];params=p['params']
        h=self.reference if url=='trusted' else self.height
        result=None
        if method=='eth_chainId':
            result={'BASE':'0x2105','BASES':'0x14a34','ETH1':'0x1','SEP1':'0xaa36a7',
                    'ARBITRUM':'0xa4b1','ARBITRUMN':'0xa4ba','ARBITRUMS':'0x66eee'}[self.chain]
            if self.chain_bad:result='0x99'
        elif method=='eth_blockNumber':result=hex(h)
        elif method=='eth_getBlockByNumber':
            n=self.earliest if params[0]=='earliest' else int(params[0],16)
            result={'number':hex(n),'hash':'0x'+'ab'*32}
        elif method=='eth_getCode':result='0x'
        elif method=='debug_getRawHeader':
            if self.addon_fail:raise RpcError('method unavailable')
            result='0x1234'
        elif method in ('trace_block','eth_supportedEntryPoints'):result=[]
        elif method=='arbtrace_block':
            if self.addon_fail:raise RpcError('method unavailable')
            result=[{'blockHash':'0x'+'ab'*32}]
        elif method=='status':result={'chain_id':'testnet' if self.chain=='NEART' else 'mainnet','sync_info':{'syncing':self.syncing}}
        elif method=='block':
            n=params.get('block_id',h)
            if n in (10000000,42376888) and not self.archive:
                return {'error':{'cause':{'name':'UNKNOWN_BLOCK'}}}
            result={'header':{'height':n,'hash':f'hash-{n}'}}
        elif method=='query':return {'error':{'cause':{'name':self.shard}}}
        else:raise AssertionError(method)
        return {'result':result}


class SpecTests(unittest.TestCase):
    def test_inherited_chain_id(self):
        for chain,expected in [('ETH1','0x1'),('BASE','0x2105'),('BASES','0x14a34'),('SEP1','0xaa36a7'),('NEART','testnet'),
                               ('ARBITRUM','0xa4b1'),('ARBITRUMN','0xa4ba'),('ARBITRUMS','0x66eee')]:
            self.assertEqual(Spec(chain).chain_rule.value['expected_value'],expected)
    def test_pruning_variants(self):
        rules={r.key:r for r in Spec('BASE').rules(())}
        self.assertEqual(rules['pruning'].mode,'pruning')
        self.assertEqual(rules['pruning@archive'].mode,'archive')
        self.assertEqual(rules['pruning'].value['latest_distance'],128)
    def test_addons_inherited_and_optional(self):
        spec=Spec('BASES')
        self.assertFalse(any('debug:' in r.key for r in spec.rules(())))
        self.assertTrue(any(r.key=='debug:enabled' for r in spec.rules(('debug',))))
        self.assertTrue(any(r.key=='trace:pruning@archive' for r in spec.rules(('trace',))))
        with self.assertRaises(ValueError):spec.rules(('unknown',))
    def test_near_testnet_inheritance(self):
        rules=Spec('NEART').rules(())
        self.assertEqual(sum(r.key.startswith('tracking-shard') for r in rules),7)
        self.assertEqual(sum(r.mode=='archive' for r in rules),2)
    def test_arbitrum_addon_and_array_parser(self):
        for chain in ('ARBITRUM','ARBITRUMN','ARBITRUMS'):
            s=Spec(chain)
            self.assertEqual(len(s.rules(())),4)
            rules={r.key:r for r in s.rules(('arbtrace','debug','trace','bundler'))}
            pd=rules['arbtrace:enabled'].directive
            self.assertEqual(json.loads(pd['function_template'])['params'],['0x152DD46'])
            self.assertEqual(parse({'result':[{'blockHash':'0xabc'}]},pd),'0xabc')
            for result in ([],None,{'0':{'blockHash':'x'}},[{}],[{'blockHash':None}],[{'blockHash':''}]):
                with self.assertRaises(RpcError):parse({'result':result},pd)
        for path in ('.result.[-1]', '.result.[*]', '.result.[9999999999]', '.result..x'):
            with self.assertRaises(ValueError):validate_parser({'parsers':[{'parse_type':'RESULT','parse_path':path}]})
    def test_invalid_parser_and_missing_import_fail_startup(self):
        source=Path(__file__).parents[1]/'rpc_checker/specs/base.json'
        with tempfile.TemporaryDirectory() as d:
            Path(d,'base.json').write_bytes(source.read_bytes())
            with self.assertRaises(ValueError):Spec('BASE',d)
        spec=Spec('BASE')
        spec.base['verifications'][0]['parse_directive']['result_parsing']['parser_func']='UNSUPPORTED'
        with self.assertRaises(ValueError):spec.rules(())


class EngineTests(unittest.TestCase):
    def engine(self,chain='BASE'):
        fake=Fake(chain);spec=Spec(chain)
        return Engine(spec,fake,adapter_for(chain)),fake
    def test_strict_height_comparison(self):
        e,f=self.engine()
        for h in (f.reference,f.reference+1):
            f.height=h;self.assertLessEqual(e.compare('node','trusted')['delta_blocks'],0)
        f.height=f.reference-1
        with self.assertRaises(RpcError):e.compare('node','trusted')
    def test_wrong_reference_chain(self):
        e,f=self.engine();f.chain_bad=True
        with self.assertRaises(RpcError):e.compare('node','trusted')
    def test_evm_pruning_boundary_and_archive(self):
        e,f=self.engine();rules={r.key:r for r in e.spec.rules(())}
        f.earliest=f.height-128;e.verify('node',rules['pruning'])
        f.earliest+=1
        with self.assertRaises(RpcError):e.verify('node',rules['pruning'])
        with self.assertRaises(RpcError):e.verify('node',rules['pruning@archive'])
        f.earliest=0;e.verify('node',rules['pruning@archive'])
    def test_near_distance_archive_and_shards(self):
        e,f=self.engine('NEAR');rules={r.key:r for r in e.spec.rules(())}
        e.verify('node',rules['pruning'])
        self.assertEqual(f.calls[-1][1]['params']['block_id'],f.height-64800)
        with self.assertRaises(RpcError):e.verify('node',rules['pruning-archive-10000000@archive'])
        f.archive=True;e.verify('node',rules['pruning-archive-10000000@archive'])
        e.verify('node',rules['tracking-shard-4'])
        f.shard='UNAVAILABLE_SHARD'
        with self.assertRaises(RpcError):e.verify('node',rules['tracking-shard-4'])
    def test_syncing_and_trustless(self):
        e,f=self.engine('NEAR');f.syncing=True
        with self.assertRaises(RpcError):e.verify('node',e.spec.chain_rule)
        e,f=self.engine();e.verify('node',next(r for r in e.spec.rules(()) if r.key=='trustless-rpc'))
    def test_null_invalid_hex_and_account_result(self):
        s=Spec('BASE');pd=s.chain_rule.directive
        for value in (None,'','not-hex'):
            with self.assertRaises(RpcError):parse({'result':value},pd)
        near=next(r for r in Spec('NEAR').rules(()) if r.key=='tracking-shard-4')
        self.assertEqual(parse({'result':{'amount':'0'}},near.directive),'0')
    def test_wrong_returned_near_block(self):
        e,f=self.engine('NEAR')
        rule=next(r for r in e.spec.rules(()) if r.key=='pruning')
        original=f.call
        def wrong(url,p):
            r=original(url,p)
            if p['method']=='block' and 'block_id' in p['params']:
                r['result']['header']['height']+=1
            return r
        with patch.object(f,'call',side_effect=wrong):
            with self.assertRaisesRegex(RpcError,'unexpected returned'):e.verify('node',rule)
    def test_untrusted_error_is_sanitized(self):
        pd=Spec('BASE').chain_rule.directive
        for cause in (None,[],{'name':'https://secret/token'},{'name':'X'*10000}):
            with self.assertRaisesRegex(RpcError,'^JSON_RPC_ERROR$'):
                parse({'error':{'cause':cause}},pd)


class ServiceTests(unittest.TestCase):
    def test_service_version(self):
        self.assertEqual(self.c.response('/healthz')[1]['version'], __version__)
        self.assertEqual(self.c.response('/status')[1]['version'], __version__)
        self.assertEqual(self.c.response('/readyz/n')[1]['version'], __version__)
    def test_arbitrum_readiness_http_ws_and_addon(self):
        for chain in ('ARBITRUM','ARBITRUMN','ARBITRUMS'):
            f=Fake(chain)
            c=Checker(Config(chain,{'n':Node('node','ws://node',('arbtrace',))},'trusted'),f)
            c.cycle('n')
            self.assertEqual(c.response('/archive/n')[0],200)
            f.addon_fail=True;c.cycle('n',False)
            self.assertEqual(c.response('/readyz/n')[0],503)
    def setUp(self):
        self.now=1000
        self.fake=Fake()
        self.cfg=Config('BASE',{'n':Node('node')},'trusted')
        self.c=Checker(self.cfg,self.fake,lambda:self.now)
    def test_readiness_levels_and_ttl(self):
        self.assertEqual(self.c.response('/readyz/n')[0],503)
        self.c.cycle('n',False)
        self.assertEqual(self.c.response('/readyz/n')[0],200)
        self.assertEqual(self.c.response('/pruning/n')[0],503)
        self.fake.earliest=10;self.c.cycle('n')
        self.assertEqual(self.c.response('/pruning/n')[0],200)
        self.assertEqual(self.c.response('/archive/n')[0],503)
        self.fake.earliest=0;self.now+=61;self.c.cycle('n')
        self.assertEqual(self.c.response('/archive/n')[0],200)
        self.now+=181;self.c.cycle('n',False)
        self.assertEqual(self.c.response('/readyz/n')[0],200)
        self.assertEqual(self.c.response('/pruning/n')[0],503)
        self.fake.chain_bad=True;self.c.cycle('n',False)
        self.assertEqual(self.c.response('/readyz/n')[0],503)
    def test_addon_and_ws_required_only_when_configured(self):
        cfg=Config('BASE',{'n':Node('node','ws://node',('debug',))},'trusted')
        c=Checker(cfg,self.fake)
        c.cycle('n');self.assertEqual(c.response('/readyz/n')[0],200)
        self.fake.addon_fail=True;c.cycle('n',False)
        self.assertEqual(c.response('/readyz/n')[0],503)
        self.fake.addon_fail=False;self.fake.ws_bad=True;c.cycle('n',False)
        self.assertEqual(c.response('/readyz/n')[0],503)
        with self.assertRaises(ValueError):Checker(Config('NEAR',{'n':Node('node','ws://node')},'trusted'),Fake('NEAR'))
    def test_aggregate_unknown_and_metrics(self):
        c=Checker(Config('BASE',{'n':Node('node'),'m':Node('node')},'trusted'),self.fake)
        c.cycle('n')
        self.assertEqual(c.response('/readyz')[0],503)
        self.assertEqual(c.response('/readyz/n')[0],200)
        self.assertEqual(c.response('/readyz/unknown')[0],404)
        self.assertEqual(c.response('/healthz')[0],200)
        self.assertIn('chain="BASE"',c.metrics())
    def test_http_readiness_route(self):
        server=make_server(self.c,('127.0.0.1',0))
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(base+'/pruning/n')
            self.assertEqual(e.exception.code,503)
            self.c.cycle('n')
            with urllib.request.urlopen(base+'/archive/n') as r:self.assertTrue(json.load(r)['ready'])
        finally:server.shutdown();server.server_close();t.join()
    def test_core_concurrency_is_bounded(self):
        c=Checker(Config('BASE',{'n':Node('node')},'trusted',workers=2),self.fake)
        release=threading.Event();both=threading.Event();lock=threading.Lock()
        active=0;peak=0
        def verify(*args):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active)
                if active==2:both.set()
            release.wait(3)
            with lock:active-=1
            return {}
        with patch.object(c.engine,'verify',side_effect=verify):
            t=threading.Thread(target=c.cycle,args=('n',False));t.start()
            try:self.assertTrue(both.wait(2))
            finally:release.set();t.join(3)
        self.assertFalse(t.is_alive());self.assertEqual(peak,2)
    def test_http_handler_limit(self):
        server=make_server(self.c,('127.0.0.1',0))
        try:
            for _ in range(server.max_handlers):self.assertTrue(server.slots.acquire(False))
            request=Mock()
            with patch.object(ThreadingHTTPServer,'process_request') as dispatch:
                server.process_request(request,('127.0.0.1',12345))
                dispatch.assert_not_called()
                request.close.assert_called_once()
        finally:
            for _ in range(server.max_handlers):server.slots.release()
            server.server_close()


class TransportTests(unittest.TestCase):
    def test_http_error_body_and_retries(self):
        cfg=Config('BASE',{},'trusted',retries=1,retry_delay=0)
        body=json.dumps({'jsonrpc':'2.0','id':1,'error':{'cause':{'name':'UNKNOWN_ACCOUNT'}}}).encode()
        err=urllib.error.HTTPError('http://node',422,'error',{},io.BytesIO(body))
        with patch('urllib.request.OpenerDirector.open',side_effect=err):
            r=RpcClient(cfg,threading.Event()).call('http://node',{'id':1})
            self.assertIn('error',r)
        with patch('urllib.request.OpenerDirector.open',side_effect=OSError('secret')) as p:
            with self.assertRaises(RpcError) as e:RpcClient(cfg,threading.Event()).call('http://node',{'id':1})
            self.assertEqual(p.call_count,2);self.assertNotIn('secret',str(e.exception))
    def test_ws_rpc_ping_subscription_and_unsubscribe(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_GET(self):
                key=self.headers['Sec-WebSocket-Key']
                accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','keep-alive, Upgrade');self.send_header('Sec-WebSocket-Accept',accept);self.end_headers()
                def send(op,data):
                    self.wfile.write(bytes([0x80|op,len(data)])+data);self.wfile.flush()
                while True:
                    head=self.rfile.read(2)
                    if not head:return
                    length=head[1]&127
                    if length==126:length=struct.unpack('!H',self.rfile.read(2))[0]
                    mask=self.rfile.read(4);raw=self.rfile.read(length)
                    if head[0]&15==10:continue
                    p=json.loads(bytes(b^mask[i%4] for i,b in enumerate(raw)))
                    result={'eth_chainId':'0x2105','eth_subscribe':'0xabc','eth_unsubscribe':True}[p['method']]
                    send(9,b'ping')
                    send(1,json.dumps({'jsonrpc':'2.0','id':p['id'],'result':result}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            client=RpcClient(Config('BASE',{},'trusted'),threading.Event())
            url=f'ws://127.0.0.1:{server.server_port}'
            self.assertEqual(client.call(url,{'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]})['result'],'0x2105')
            self.assertTrue(client.subscription(url)['subscription'])
        finally:server.shutdown();server.server_close();t.join()
    def test_bad_envelope(self):
        with self.assertRaises(RpcError):RpcClient.envelope({'jsonrpc':'2.0','id':2,'result':'x'},{'id':1})
        for value in (True,1.0,'1',None):
            with self.assertRaises(RpcError):RpcClient.envelope({'jsonrpc':'2.0','id':value,'result':'x'},{'id':1})
    def test_redirect_is_not_followed(self):
        hits=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                hits.append(self.path)
                self.send_response(307)
                self.send_header('Location','/private')
                self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            client=RpcClient(Config('BASE',{},'trusted',retries=0),threading.Event())
            with self.assertRaises(RpcError):
                client.call(f'http://127.0.0.1:{server.server_port}/rpc',{'id':1})
            self.assertEqual(hits,['/rpc'])
        finally:server.shutdown();server.server_close();t.join()
    def test_body_limit_and_deadline(self):
        client=RpcClient(Config('BASE',{},'trusted',timeout=1,retries=0),threading.Event())
        for oversized in (True,False):
            response=Mock()
            response.__enter__=Mock(return_value=response)
            response.__exit__=Mock(return_value=False)
            response.read1.return_value=b'x'*65536 if oversized else b' '
            clock=patch('rpc_checker.rpc.time.monotonic',return_value=0) if oversized else patch('rpc_checker.rpc.time.monotonic',side_effect=[0,0,2])
            with patch.object(client.opener,'open',return_value=response),clock:
                with self.assertRaises(RpcError):client.call('http://node',{'id':1})
            response.__exit__.assert_called_once()


class ConfigTests(unittest.TestCase):
    def test_arbitrum_requires_reference(self):
        for chain in ('ARBITRUM','ARBITRUMN','ARBITRUMS'):
            with patch.dict(os.environ,{'CHAIN_ID':chain,'NODE_RPC_URL':'http://node'},clear=True):
                with self.assertRaises(ValueError):Config.from_env()
                os.environ['TRUSTED_RPC_URL']='https://reference'
                self.assertEqual(Config.from_env().chain_id,chain)
    def test_url_and_resource_validation(self):
        for url in ('http://node:99999','http://node:0','http://u:p@node','http://node/\r\nInjected:x','http://node/#x'):
            with patch.dict(os.environ,{'CHAIN_ID':'BASE','NODE_RPC_URL':url},clear=True):
                with self.assertRaises(ValueError):Config.from_env()
        for value in ('-1','6','1000000'):
            with patch.dict(os.environ,{'CHAIN_ID':'BASE','NODE_RPC_URL':'http://node','RPC_RETRY_COUNT':value},clear=True):
                with self.assertRaises(ValueError):Config.from_env()
    def test_config(self):
        with patch.dict(os.environ,{'CHAIN_ID':'BASES','NODE_RPC_URL':'http://node','ADDONS':'debug,trace'},clear=True):
            c=Config.from_env();self.assertEqual(c.trusted,'https://sepolia.base.org');self.assertEqual(c.nodes['default'].addons,('debug','trace'))
        for env in ({'CHAIN_ID':'other'}, {'RPC_TIMEOUT_SECONDS':'nan'}, {'NODES_JSON':'{}'}):
            with patch.dict(os.environ,{'CHAIN_ID':'NEAR','NODE_RPC_URL':'http://node',**env},clear=True):
                with self.assertRaises(ValueError):Config.from_env()


if __name__=='__main__':unittest.main()
