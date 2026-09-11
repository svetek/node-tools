import json
import time
import urllib.error
import urllib.request


class RpcError(Exception):
    pass


class RpcClient:
    def __init__(self, config, stop):
        self.config, self.stop = config, stop

    def call(self, url, payload):
        last = None
        for attempt in range(self.config.retries + 1):
            if self.stop.is_set():
                raise RpcError('stopping')
            try:
                request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json', 'User-Agent': 'near-rpc-checker/0.1'})
                try:
                    response = urllib.request.urlopen(request, timeout=self.config.timeout)
                except urllib.error.HTTPError as exc:
                    # NEAR can return JSON-RPC errors such as UNKNOWN_ACCOUNT with HTTP 4xx.
                    if not 400 <= exc.code < 500 or exc.code == 429:
                        raise
                    response = exc
                with response:
                    body = response.read(4_194_305)
                if len(body) > 4_194_304:
                    raise RpcError('response exceeds 4 MiB')
                result = json.loads(body)
                if not isinstance(result, dict) or result.get('jsonrpc') != '2.0' or result.get('id') != payload['id']:
                    raise RpcError('invalid JSON-RPC envelope')
                if ('result' in result) == ('error' in result):
                    raise RpcError('expected exactly one of result/error')
                return result
            except (OSError, ValueError, RpcError) as exc:
                last = exc
                if attempt < self.config.retries:
                    self.stop.wait(self.config.retry_delay)
        # Do not expose URLs (which may contain credentials) in errors/metrics.
        raise RpcError(f'RPC transport/response failure: {type(last).__name__}')


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
