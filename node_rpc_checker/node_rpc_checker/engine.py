import json
import re
from .rpc import RpcError


def number(value):
    if type(value) is int and value >= 0: return value
    if isinstance(value,str) and re.fullmatch(r'0x[0-9a-fA-F]+|[0-9]+',value):
        return int(value,16 if value.startswith('0x') else 10)
    raise RpcError('invalid nonnegative block number')


def error_name(response):
    e=response.get('error',{})
    cause = e.get('cause') if isinstance(e, dict) else None
    name = cause.get('name') if isinstance(cause, dict) else None
    # Upstream-controlled diagnostics must not leak arbitrary response content.
    return name if isinstance(name, str) and re.fullmatch(r'[A-Z][A-Z_0-9]{0,63}', name) else 'JSON_RPC_ERROR'


def matches(actual,expected,encoding=None):
    if actual is None: return False
    if expected=='*': return actual!=''
    if encoding=='hex':
        return number(actual)==number(expected)
    return str(actual)==str(expected)


def parse(response,pd):
    alternatives=pd.get('parsers')
    if alternatives:
        for parser in alternatives:
            value=response
            try:
                for key in parser['parse_path'].lstrip('.').split('.'):
                    if key.startswith('['):
                        if not isinstance(value, list):raise TypeError
                        value = value[int(key[1:-1])]
                    else:
                        if not isinstance(value, dict):raise TypeError
                        value = value[key]
            except (KeyError,TypeError,IndexError):continue
            if matches(value,parser['value']):return value
        raise RpcError(str(error_name(response)))
    if 'error' in response:raise RpcError(str(error_name(response)))
    value=response.get('result')
    rp=pd['result_parsing']
    try:
        for key in rp['parser_arg'][1:]:value=value[key]
    except (KeyError,TypeError):raise RpcError('result parse failed') from None
    if value is None or value == '':raise RpcError('empty result')
    if rp.get('encoding')=='hex':
        if not isinstance(value,str) or not re.fullmatch(r'0x[0-9a-fA-F]*',value):
            raise RpcError('invalid hex result')
    # Lava's NEAR hash parser declares base64; preserve the returned opaque hash.
    # Hash existence/comparison requires no re-encoding in this checker.
    return value


class Engine:
    def __init__(self,spec,client,adapter):
        self.spec,self.client,self.adapter=spec,client,adapter

    def height(self,url):
        pd=self.spec.directives['GET_BLOCKNUM']
        return number(parse(self.client.call(url,json.loads(pd['function_template'])),pd))

    def verify(self,url,rule):
        pd,value=rule.directive,rule.value
        latest=None
        if value.get('latest_distance'):
            latest=self.height(url)
        template=pd['function_template']
        if pd['function_tag']=='GET_BLOCK_BY_NUM':
            target=latest-value['latest_distance'] if latest is not None else number(value['expected_value'])
            if target<0:raise RpcError('height below requested pruning distance')
            template=template % target
        response=self.client.call(url,json.loads(template))
        actual=parse(response,pd)
        if pd['function_tag']=='GET_BLOCK_BY_NUM':
            result = response.get('result')
            if pd.get('api_name') == 'block':
                header = result.get('header') if isinstance(result, dict) else None
                returned = header.get('height') if isinstance(header, dict) else None
            elif pd.get('api_name') == 'eth_getBlockByNumber':
                returned = result.get('number') if isinstance(result, dict) else None
            else:
                raise RpcError('unsupported block identity validation')
            if number(returned) != target:
                raise RpcError('unexpected returned block height')
        if rule.key=='chain-id':self.adapter.check_status(response)
        if latest is not None and pd['function_tag']!='GET_BLOCK_BY_NUM':
            earliest=number(actual)
            if latest-earliest<value['latest_distance']:
                raise RpcError('insufficient retained block history')
        expected=value.get('expected_value','*')
        if pd['function_tag']!='GET_BLOCK_BY_NUM' and not matches(actual,expected,pd.get('result_parsing',{}).get('encoding')):
            raise RpcError('verification value mismatch')
        if isinstance(actual,(list,dict)):
            return {'value_type':type(actual).__name__,'items':len(actual)}
        return {'value':str(actual)[:256]}

    def compare(self,url,trusted):
        self.verify(trusted,self.spec.chain_rule)
        reference=self.height(trusted)
        local=self.height(url)
        if local<reference:raise RpcError(f'node behind: node={local}, trusted={reference}, lag={reference-local}')
        return {'node_height':local,'trusted_height':reference,'delta_blocks':reference-local}
