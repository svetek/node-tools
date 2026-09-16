from node_rpc_checker.rpc import RpcError


class Fake:
    def __init__(self, chain="BASE"):
        self.chain = chain
        self.height = 100000000
        self.reference = 100000000
        self.earliest = 0
        self.archive = False
        self.shard = "UNKNOWN_ACCOUNT"
        self.syncing = False
        self.chain_bad = False
        self.addon_fail = False
        self.ws_bad = False
        self.calls = []

    def subscription(self, url, subscribe, unsubscribe):
        if self.ws_bad:
            raise RpcError("WS failed")
        return {"subscription": True}

    def call(self, url, p):
        self.calls.append((url, p))
        method = p["method"]
        params = p["params"]
        h = self.reference if url == "trusted" else self.height
        result = None
        if method == "eth_chainId":
            result = {
                "BASE": "0x2105",
                "BASES": "0x14a34",
                "ETH1": "0x1",
                "SEP1": "0xaa36a7",
                "ARBITRUM": "0xa4b1",
                "ARBITRUMN": "0xa4ba",
                "ARBITRUMS": "0x66eee",
                "POLYGON": "0x89",
                "POLYGONA": "0x13882",
            }[self.chain]
            if self.chain_bad:
                result = "0x99"
        elif method == "eth_blockNumber":
            result = hex(h)
        elif method == "eth_getBlockByNumber":
            n = self.earliest if params[0] == "earliest" else int(params[0], 16)
            result = {"number": hex(n), "hash": "0x" + "ab" * 32}
        elif method == "eth_getCode":
            result = "0x"
        elif method == "debug_getRawHeader":
            if self.addon_fail:
                raise RpcError("method unavailable")
            result = "0x1234"
        elif method in ("trace_block", "eth_supportedEntryPoints"):
            result = []
        elif method == "arbtrace_block":
            if self.addon_fail:
                raise RpcError("method unavailable")
            result = [{"blockHash": "0x" + "ab" * 32}]
        elif method == "status":
            result = {
                "chain_id": "testnet" if self.chain == "NEART" else "mainnet",
                "sync_info": {"syncing": self.syncing},
            }
        elif method == "block":
            n = params.get("block_id", h)
            if n in (10000000, 42376888) and not self.archive:
                return {"error": {"cause": {"name": "UNKNOWN_BLOCK"}}}
            result = {"header": {"height": n, "hash": f"hash-{n}"}}
        elif method == "query":
            return {"error": {"cause": {"name": self.shard}}}
        else:
            raise AssertionError(method)
        return {"result": result}
