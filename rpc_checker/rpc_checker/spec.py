"""Fail-closed loader for the constructs in the bundled Lava specifications."""
import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Rule:
    key: str
    mode: str
    directive: dict
    value: dict


def validate_parser(pd):
    if pd.get('parsers'):
        for p in pd['parsers']:
            if p.get('parse_type') != 'RESULT' or not re.fullmatch(r'(\.(?:[A-Za-z_][A-Za-z_0-9]*|\[(?:0|[1-9][0-9]{0,8})\]))+',p.get('parse_path','')):
                raise ValueError('unsupported alternative parser')
        return
    p = pd.get('result_parsing', {})
    if p.get('parser_func') not in ('PARSE_BY_ARG','PARSE_CANONICAL'):
        raise ValueError('unsupported result parser')
    args = p.get('parser_arg', [])
    if not args or args[0] != '0' or (p['parser_func']=='PARSE_BY_ARG' and args!=['0']):
        raise ValueError('unsupported parser arguments')
    if p.get('encoding') not in (None,'','hex','base64'):
        raise ValueError('unsupported encoding')


class Spec:
    def __init__(self, chain_id, directory=None):
        directory = directory or Path(__file__).with_name('specs')
        specs, self.hashes = {}, {}
        for path in sorted(Path(directory).glob('*.json')):
            raw=path.read_bytes()
            self.hashes[path.name]=hashlib.sha256(raw).hexdigest()
            for s in json.loads(raw)['proposal']['specs']:
                if s['index'] in specs: raise ValueError('duplicate chain ID')
                specs[s['index']]=s
        def resolve(index, visiting=()):
            if index in visiting: raise ValueError('cyclic spec imports')
            if index not in specs: raise ValueError('missing imported spec: '+index)
            s=specs[index]
            if not s.get('enabled'): raise ValueError('disabled spec: '+index)
            collections={}
            for parent in s.get('imports',[]) or []:
                for key,c in resolve(parent,visiting+(index,)).items():
                    merge(collections,key,c)
            for c in s['api_collections']:
                data=c['collection_data']
                key=tuple(data.get(k,'') for k in ('api_interface','type','internal_path','add_on'))
                merge(collections,key,c)
            return collections
        def merge(collections,key,child):
            previous=collections.get(key,{})
            merged=copy.deepcopy(previous)
            for k,v in child.items():
                if k in ('parse_directives','verifications'):
                    field='function_tag' if k=='parse_directives' else 'name'
                    entries={e[field]:copy.deepcopy(e) for e in previous.get(k,[]) or []}
                    for e in v or []:
                        entries[e[field]]={**entries.get(e[field],{}),**copy.deepcopy(e)}
                    merged[k]=list(entries.values())
                elif v is not None:
                    merged[k]=copy.deepcopy(v)
            collections[key]=merged
        self.collections=resolve(chain_id)
        self.base=self.collections[('jsonrpc','POST','','')]
        self.directives={d['function_tag']:d for d in self.base.get('parse_directives',[])}
        for tag in ('GET_BLOCKNUM','GET_BLOCK_BY_NUM'):
            validate_parser(self.directives[tag])
        self.chain_rule=next(r for r in self.rules(()) if r.key=='chain-id')

    def rules(self, addons):
        available={k[3] for k,c in self.collections.items() if c.get('enabled')}
        if set(addons)-available: raise ValueError('unknown or disabled addon')
        rules=[]
        for (interface,method,path,addon),c in self.collections.items():
            if addon and addon not in addons: continue
            if not c.get('enabled'): continue
            if (interface,method,path)!=('jsonrpc','POST',''):
                raise ValueError('unsupported selected API collection')
            for v in c.get('verifications',[]) or []:
                pd=v.get('parse_directive',{})
                tag=pd.get('function_tag')
                if tag not in ('VERIFICATION','GET_BLOCK_BY_NUM','GET_EARLIEST_BLOCK'):
                    raise ValueError('unsupported verification tag')
                directive={**self.directives.get(tag,{}),**pd}
                if not directive.get('function_template'): raise ValueError('missing function template')
                template=directive['function_template']
                rendered=template.replace('%d','1').replace('%x','1')
                if '%' in rendered: raise ValueError('unsupported verification template placeholder')
                request=json.loads(rendered)
                if request.get('jsonrpc')!='2.0' or not isinstance(request.get('method'),str) or 'id' not in request:
                    raise ValueError('invalid verification request template')
                validate_parser(directive)
                for value in v.get('values',[]):
                    if set(value)-{'expected_value','latest_distance','extension'}:
                        raise ValueError('unsupported verification value')
                    extension=value.get('extension','')
                    if extension not in ('','archive'): raise ValueError('unsupported extension')
                    if 'latest_distance' in value and (type(value['latest_distance']) is not int or value['latest_distance'] <= 0):
                        raise ValueError('invalid latest_distance')
                    if not value.get('latest_distance') and 'expected_value' not in value:
                        raise ValueError('verification has no condition')
                    mode='archive' if extension else ('pruning' if value.get('latest_distance') else 'readyz')
                    key=(addon+':' if addon else '')+v['name']+('@archive' if extension else '')
                    if any(r.key==key for r in rules): raise ValueError('duplicate verification key')
                    rules.append(Rule(key,mode,directive,value))
        return rules
