# rpc-checker

Service version: **1.1.0**. Release image: `svetekllc/rpc-checker:1.1.0`.
Version is defined in `rpc_checker/__init__.py`, used by package metadata and
RPC User-Agent, and exposed in `/healthz`, `/status` and readiness responses.
The Docker build checks that its VERSION label matches the service version.

Universal NEAR/EVM RPC readiness service driven by bundled Lava specifications.
Python 3.11+, no third-party runtime dependencies. One chain per service instance,
multiple named nodes per instance. Use separate instances for separate chains.

## Layout and launch

- `rpc_checker/`: Python package, engine, adapters, HTTP/WS transports.
- `rpc_checker/specs/`: bundled near.json, ethereum.json, base.json, arbitrum.json.
- `tests/`: unit and local HTTP/WS integration tests.
- `legacy/near`, `legacy/evm_checker`: preserved standalone implementations.

Run from this directory:

```bash
CHAIN_ID=BASE NODE_RPC_URL=http://192.0.2.10:8545 python3 -m rpc_checker
CHAIN_ID=NEAR NODE_RPC_URL=http://192.0.2.11:3030 python3 -m rpc_checker
```

Docker: copy `.env.example` to `.env`, configure reachable upstream addresses,
then run `docker compose up -d --build`. Container localhost means the container,
not the host. Compose binds the monitoring API to host loopback by default.
From the repository root:

```bash
docker build -t rpc-checker:latest rpc_checker
```

## Chain selection

| CHAIN_ID | Expected network ID | Inheritance | Default trusted HTTP RPC |
| --- | --- | --- | --- |
| NEAR | mainnet | NEAR | https://rpc.mainnet.near.org |
| NEART | testnet | NEAR → NEART | https://rpc.testnet.near.org |
| ETH1 | 0x1 | ETH1 | explicitly set TRUSTED_RPC_URL |
| SEP1 | 0xaa36a7 | ETH1 → SEP1 | explicitly set TRUSTED_RPC_URL |
| BASE | 0x2105 | ETH1 → BASE | https://mainnet.base.org |
| BASES | 0x14a34 | ETH1 → BASE → BASES | https://sepolia.base.org |
| ARBITRUM | 0xa4b1 | ETH1 → ARBITRUM | explicitly set TRUSTED_RPC_URL |
| ARBITRUMN | 0xa4ba | ETH1 → ARBITRUM → ARBITRUMN | explicitly set TRUSTED_RPC_URL |
| ARBITRUMS | 0x66eee | ETH1 → ARBITRUM → ARBITRUMS | explicitly set TRUSTED_RPC_URL |

ARBITRUMN selects chain ID 42170 (Nova); the snapshot's name contains
"testnet", but network matching uses the ID, not that descriptive label.
ARBITRUMS selects Sepolia (421614). Use a reference for the same network.

HOL1 (0x4268) is also present in the source spec; loading it does not imply
this historical network still has operational public RPCs.

Snapshots retrieved 2026-09-11:
[NEAR](https://github.com/lavanet/lava/blob/main/specs/mainnet-1/specs/near.json),
[Ethereum](https://github.com/lavanet/lava/blob/main/specs/mainnet-1/specs/ethereum.json),
[Base](https://github.com/lavanet/lava/blob/main/specs/mainnet-1/specs/base.json),
[Arbitrum](https://github.com/lavanet/lava/blob/main/specs/mainnet-1/specs/arbitrum.json).
SHA-256 hashes are exposed in /status. No runtime GitHub/Lava access is needed.
The on-chain spec used by a provider may differ from these snapshots.

Collections merge by interface, method, internal path and addon; verifications
by name; directives by function tag. Child values replace parent values, while
missing directives remain inherited. Every verification value becomes a separate
rule, preserving ordinary and archive variants under the same name.

Unsupported selected collections, parsers, extensions, templates, missing imports
and cycles cause startup failure. This is not a full interpreter for every future
Lava construct. Supported result parsers: PARSE_BY_ARG, PARSE_CANONICAL, dotted
RESULT alternatives, including nonnegative array indices such as `.result.[0].blockHash`.
Hex values are validated; NEAR hashes remain opaque despite
the spec's base64 annotation. This service does not build Lava finalization proofs.

NEART inherits the named archive probe at 10000000 and adds 42376888: both are
required for archive with this snapshot. Shard account names keep their .near
suffixes exactly as supplied by the spec.

## Readiness endpoints

| Endpoint (also accepts /<node>) | Required successful, fresh checks |
| --- | --- |
| /readyz | Core rules + target height >= trusted height |
| /pruning | Core readiness + ordinary retention conditions |
| /archive | Pruning readiness + archive conditions |
| /status | Always 200 for known nodes; all checks and readiness levels |
| /healthz | Process liveness only, no node suffix |
| /metrics | Prometheus gauges, no node suffix |

Missing, failed, or expired required results yield **503**; unknown paths/nodes
yield **404**. Aggregate readiness requires **all** configured nodes. For HAProxy,
use per-node /pruning/node-01 or /archive/node-01. /status.ready describes core
readiness; nodes.<name>.readiness contains all three levels.

- NEAR core: status chain-id, syncing=false, seven view_account queries.
  UNKNOWN_ACCOUNT or parsed account amount passes; UNAVAILABLE_SHARD fails.
  Height uses block(finality=final). Pruning requests H−64800; archive uses
  fixed block heights from the spec.
  Historical block responses must also contain the requested block height.
- EVM core: eth_chainId and trustless-rpc (eth_getCode on the zero address).
  Height uses eth_blockNumber. Pruning requires H−earliest >=128;
  archive requires earliest==0. Genesis availability does not prove historical
  state access: these are the spec probes, not exhaustive archive tests.
- The trusted chain is verified before reading reference height, including NEAR
  syncing status. Target height is read afterwards. **Even one block behind
  fails**; ahead passes. No MAX_BEHIND_BLOCKS option or positive QoS lag allowance.

Core, pruning and archive have independent workers per node. Slow archive
requests do not block core polling. HTTP health requests only inspect cached
state. Explicit failures replace old success immediately, including transport
failures after retries. TTL uses monotonic age from the start of an attempt.
Independent core rules run concurrently within a bounded per-node pool, so a
slow shard probe does not serially delay every other rule.

## Optional addons and WS

EVM addons are explicitly selected per node:

- debug: debug_getRawHeader(latest).
- trace: trace_block(latest), plus its own pruning/archive conditions.
- bundler: eth_supportedEntryPoints.
- arbtrace (Arbitrum family): arbtrace_block("0x152DD46"), requiring a nonempty
  `.result.[0].blockHash`. Empty arrays fail this probe. This exact historical
  probe is inherited by Nova/Sepolia too; it is not replaced with a recent block.
  Enable only when this addon is required; normal readiness does not require it.

Only selected addons affect readiness. Archive-tagged addon conditions only
affect /archive. Empty trace/entry-point arrays satisfy the spec's wildcard,
not a guarantee of useful bundler service. No transactions are submitted.

If websocket_url is configured, all selected rules and height checks run over
both HTTP and WS. An eth_subscribe(newHeads) acknowledgement followed by a
successful eth_unsubscribe on the same connection is required too. It does not
wait for an actual block event. Other WS calls open new connections; latency
includes handshake. NEAR rejects WS settings because its spec has no subscription
directives. WSS validates certificates. WS supports fragmented text, ping/pong,
masked client frames, size limits and a read deadline.

HTTP uses environment proxy settings; WS connects directly. Configure NO_PROXY
where appropriate. Access from a VPN/whitelisted source is not proof of universal
internet access.

## Configuration

Set exactly one of NODE_RPC_URL or NODES_JSON. Single-node mode uses name
default; WEBSOCKET_URL and comma-separated ADDONS apply to it. Multi-node example:

```json
{
  "base-01": {"rpc_url": "http://192.0.2.10:8545"},
  "base-02": {
    "rpc_url": "http://192.0.2.11:8545",
    "websocket_url": "ws://192.0.2.11:8546",
    "addons": ["debug"]
  }
}
```

| Variable | Default |
| --- | --- |
| CHAIN_ID | required, see table |
| TRUSTED_RPC_URL | chain-specific above, overridable |
| POLL_INTERVAL_SECONDS | 5 seconds between core cycles |
| DEEP_CHECK_INTERVAL_SECONDS | 60 seconds between deep cycles |
| STATE_TTL_SECONDS | 30 seconds for core |
| DEEP_STATE_TTL_SECONDS | 180 seconds, must exceed deep interval |
| RPC_TIMEOUT_SECONDS | 3 seconds |
| RPC_RETRY_COUNT | 2 extra attempts for transport/invalid-envelope errors; range 0–5 |
| CHECK_WORKERS | 4 concurrent core checks per node; range 1–32 |
| RETRY_DELAY_SECONDS | 0.5 seconds |
| HTTP_HOST / HTTP_PORT | 0.0.0.0 / 8080 |

NEAR HTTP 4xx JSON errors are parsed to preserve UNKNOWN_ACCOUNT.
HTTP 429/5xx and transport failures are retried. Semantic failures are retried
next scheduled cycle. Subscription is attempted once per core cycle.
Tune intervals/timeouts/TTLs for upstream latency and quotas; WS/addons multiply
request counts. EVM eth_syncing is not a rule in these supplied specs.

Metrics prefix: rpc_checker_, with chain/node and mode or check labels.
Metrics include readiness, check success/freshness, latency, timestamps and HTTP
height/delta. RPC URLs are not exposed in metrics or errors.

## Security and operational limits

- Configuration is operator-trusted. RPC URLs cannot be supplied by incoming
  health requests. Private upstream IPs are intentionally allowed; restrict
  egress with firewall/network policy to approved RPCs and trusted DNS/proxies.
- HTTP redirects are rejected. URLs reject userinfo, whitespace/control
  characters, invalid ports and fragments. Percent-encode path/query tokens;
  protect the environment file and prefer HTTPS/WSS for credentials.
- JSON-RPC IDs must match both type and value. HTTP responses are capped at
  4 MiB, WS messages at 1 MiB. Upstream error names are length/character bounded.
  HTTP body reads have an elapsed-time guard; DNS, connect and HTTP header
  processing do not have a hard end-to-end deadline. Use a trusted egress proxy
  with total-request deadlines when checking hostile endpoints.
- The monitoring server allows at most 32 active handlers and a 5-second socket
  inactivity timeout; excess connections are closed. It has no authentication
  or TLS: keep Compose's loopback binding, or use a protected reverse proxy.
  Do not expose the stdlib monitoring server directly to the public internet.
- Up to 64 configured nodes, names up to 64 characters. Core worker pools are
  reused and bounded **per node**, not globally; deep workers are independent.
  Size node counts and CHECK_WORKERS to the host and RPC rate limits.
- These changes and regression tests are a code review, not a penetration test
  or a guarantee that a remote node is honest. Archive probes establish only
  the historical availability covered by the Lava specification.

## Migration and tests

Old implementations/configs are retained in legacy/ and excluded from the new
image/package. Image/module now: rpc-checker / python3 -m rpc_checker.
NEAR_NETWORK becomes CHAIN_ID=NEAR or NEART; EVM needs its explicit spec ID.
Metrics change from near_rpc_checker_* or evm_height_checker_* to rpc_checker_*.
Update dashboards/alerts separately; the old EVM Grafana dashboard remains
unchanged for legacy deployments. HTTP paths remain; EVM readiness now requires
spec checks, not just height/WS upgrade. Unlike legacy EVM, known failures
immediately invalidate readiness rather than preserving old success.

No services, HAProxy configurations or Kubernetes resources are deployed/changed
by this repository migration.

```bash
python3 -m unittest discover -s tests -v
```
