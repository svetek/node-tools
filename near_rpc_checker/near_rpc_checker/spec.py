"""Resolve the bundled Lava specification, including named inherited verifications."""
import copy
import hashlib
import json
from pathlib import Path

SOURCE = 'https://github.com/lavanet/lava/blob/main/specs/mainnet-1/specs/near.json'


def load_spec(network):
    raw = Path(__file__).with_name('near.json').read_bytes()
    specs = {s['index']: s for s in json.loads(raw)['proposal']['specs']}
    def resolve(index):
        checks, directives = {}, {}
        for parent in specs[index].get('imports', []):
            pc, pd = resolve(parent)
            checks.update(pc)
            directives.update(pd)
        for collection in specs[index]['api_collections']:
            c = collection['collection_data']
            if not collection['enabled'] or c['api_interface'] != 'jsonrpc' or c.get('add_on'):
                continue
            for check in collection.get('verifications', []):
                merged = copy.deepcopy(checks.get(check['name'], {}))
                merged.update(check)
                checks[check['name']] = merged
            for directive in collection.get('parse_directives', []):
                directives[directive['function_tag']] = directive
        return checks, directives
    checks, directives = resolve({'mainnet': 'NEAR', 'testnet': 'NEART'}[network])
    return checks, directives, hashlib.sha256(raw).hexdigest()
