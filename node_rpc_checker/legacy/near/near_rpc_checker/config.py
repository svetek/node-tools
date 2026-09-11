import json
import math
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    network: str
    nodes: dict[str, str]
    trusted: str
    poll: float = 5
    deep_interval: float = 60
    ttl: float = 30
    deep_ttl: float = 180
    timeout: float = 3
    retries: int = 2
    retry_delay: float = 0.5
    host: str = '0.0.0.0'
    port: int = 8080

    @classmethod
    def from_env(cls):
        network = os.getenv('NEAR_NETWORK', 'mainnet')
        if network not in ('mainnet', 'testnet'):
            raise ValueError('NEAR_NETWORK must be mainnet or testnet')
        single, multi = os.getenv('NODE_RPC_URL', ''), os.getenv('NODES_JSON', '')
        if bool(single) == bool(multi):
            raise ValueError('set exactly one of NODE_RPC_URL and NODES_JSON')
        raw = json.loads(multi) if multi else {'default': {'rpc_url': single}}
        if not isinstance(raw, dict) or not raw:
            raise ValueError('NODES_JSON must be a nonempty object')
        nodes = {}
        for name, value in raw.items():
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
                raise ValueError('invalid node name')
            if not isinstance(value, dict) or not isinstance(value.get('rpc_url'), str):
                raise ValueError('each node requires rpc_url')
            nodes[name] = value['rpc_url']
        trusted = os.getenv('TRUSTED_RPC_URL', f'https://rpc.{network}.near.org')
        for url in [trusted, *nodes.values()]:
            p = urlsplit(url)
            if p.scheme not in ('http', 'https') or not p.hostname or p.fragment:
                raise ValueError('RPC URLs must be HTTP(S) URLs without fragments')
        values = {}
        for field, env, default in [
            ('poll', 'POLL_INTERVAL_SECONDS', 5),
            ('deep_interval', 'DEEP_CHECK_INTERVAL_SECONDS', 60),
            ('ttl', 'STATE_TTL_SECONDS', 30),
            ('deep_ttl', 'DEEP_STATE_TTL_SECONDS', 180),
            ('timeout', 'RPC_TIMEOUT_SECONDS', 3),
            ('retry_delay', 'RETRY_DELAY_SECONDS', 0.5),
        ]:
            v = float(os.getenv(env, str(default)))
            if not math.isfinite(v) or v < 0 or (v == 0 and field != 'retry_delay'):
                raise ValueError(f'invalid {env}')
            values[field] = v
        retries = int(os.getenv('RPC_RETRY_COUNT', '2'))
        port = int(os.getenv('HTTP_PORT', '8080'))
        if retries < 0 or not 1 <= port <= 65535:
            raise ValueError('invalid retries or HTTP_PORT')
        if values['deep_ttl'] <= values['deep_interval']:
            raise ValueError('DEEP_STATE_TTL_SECONDS must exceed DEEP_CHECK_INTERVAL_SECONDS')
        return cls(network, nodes, trusted, **values, retries=retries,
                   host=os.getenv('HTTP_HOST', '0.0.0.0'), port=port)
