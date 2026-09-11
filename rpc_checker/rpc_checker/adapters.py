from .rpc import RpcError


class Near:
    websocket = False
    def check_status(self,response):
        if response.get('result',{}).get('sync_info',{}).get('syncing') is not False:
            raise RpcError('node is syncing or sync status missing')


class Evm:
    websocket = True
    def check_status(self,response):
        pass


def adapter_for(chain_id):
    return Near() if chain_id in ('NEAR','NEART') else Evm()
