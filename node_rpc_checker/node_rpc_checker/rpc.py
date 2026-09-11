import json
import time
import urllib.error
import urllib.request
from http.client import HTTPException
from .websocket import WebSocketConnection
from . import __version__


class RpcError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise RpcError('RPC redirects are disabled')


class RpcClient:
    def __init__(self, config, stop):
        self.config, self.stop = config, stop
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, url, payload):
        last = None
        for attempt in range(self.config.retries + 1):
            if self.stop.is_set():
                raise RpcError('stopping')
            try:
                if url.startswith(('ws://','wss://')):
                    with WebSocketConnection(url,self.config.timeout) as ws:
                        ws.send_json(payload)
                        return self.envelope(ws.receive_json(),payload)
                request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json', 'User-Agent': f'node-rpc-checker/{__version__}'})
                try:
                    response = self.opener.open(request, timeout=self.config.timeout)
                except urllib.error.HTTPError as exc:
                    # NEAR can return JSON-RPC errors such as UNKNOWN_ACCOUNT with HTTP 4xx.
                    if not 400 <= exc.code < 500 or exc.code == 429:
                        exc.close()
                        raise
                    response = exc
                with response:
                    # read1 returns after one buffered/raw read; a trickling body
                    # cannot keep resetting an inactivity timeout indefinitely.
                    deadline = time.monotonic() + self.config.timeout
                    body = bytearray()
                    while True:
                        if self.stop.is_set():raise RpcError('stopping')
                        if time.monotonic() >= deadline:raise RpcError('HTTP body deadline exceeded')
                        chunk = response.read1(min(65536, 4_194_305 - len(body)))
                        if not chunk:break
                        body.extend(chunk)
                        if len(body) > 4_194_304:
                            raise RpcError('response exceeds 4 MiB')
                return self.envelope(json.loads(body),payload)
            except (OSError, ValueError, RuntimeError, HTTPException, RpcError) as exc:
                last = exc
                if attempt < self.config.retries:
                    self.stop.wait(self.config.retry_delay)
        # Do not expose URLs (which may contain credentials) in errors/metrics.
        raise RpcError(f'RPC transport/response failure: {type(last).__name__}')

    @staticmethod
    def envelope(result,payload):
        if (not isinstance(result,dict) or result.get('jsonrpc')!='2.0'
                or type(result.get('id')) is not type(payload['id']) or result.get('id')!=payload['id']):
            raise RpcError('invalid JSON-RPC envelope')
        if ('result' in result)==('error' in result):raise RpcError('expected exactly one of result/error')
        return result

    def subscription(self,url):
        try:
            with WebSocketConnection(url,self.config.timeout) as ws:
                p={'jsonrpc':'2.0','id':1,'method':'eth_subscribe','params':['newHeads']}
                ws.send_json(p)
                r=self.envelope(ws.receive_json(),p)
                sub=r.get('result')
                if not isinstance(sub,str) or not sub:raise RpcError('subscription rejected')
                p={'jsonrpc':'2.0','id':2,'method':'eth_unsubscribe','params':[sub]}
                ws.send_json(p)
                while True:
                    r=ws.receive_json()
                    if isinstance(r,dict) and r.get('method')=='eth_subscription':continue
                    r=self.envelope(r,p)
                    if r.get('result') is not True:raise RpcError('unsubscribe rejected')
                    return {'subscription':True}
        except (OSError,ValueError,RuntimeError) as exc:
            raise RpcError(f'WebSocket subscription failed: {type(exc).__name__}') from None


def result_of(response):
    if 'error' in response:
        error = response['error']
        cause = error.get('cause', {}) if isinstance(error, dict) else {}
        raise RpcError(str(cause.get('name', 'JSON_RPC_ERROR')))
    if not isinstance(response.get('result'), dict):
        raise RpcError('expected object result')
    return response['result']


def header_of(response, expected=None):
    header = result_of(response).get('header', {})
    height = header.get('height')
    if type(height) is not int or height < 0 or not isinstance(header.get('hash'), str) or not header['hash']:
        raise RpcError('invalid block header')
    if expected is not None and height != expected:
        raise RpcError('unexpected block height')
    return header
