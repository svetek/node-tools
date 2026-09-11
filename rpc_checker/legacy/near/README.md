# near-rpc-checker

Dependency-free Python 3.11+ service for NEAR mainnet/testnet. Mirrors the EVM
checker's named-node HTTP health interface, but uses NEAR JSON-RPC and bundled
Lava verification rules. It does not submit transactions or change node settings.

## Readiness

* `status` must report the configured chain and `syncing=false`.
* Seven `query/view_account` probes must return account state (`result.amount`)
  or `error.cause.name=UNKNOWN_ACCOUNT`. `UNAVAILABLE_SHARD` fails readiness.
* Final height from `block({"finality":"final"})` must be **equal to or higher
  than the trusted node**. No positive lag allowance is configurable. The trusted
  node's chain and syncing status are checked first; target height is read after
  reference height to reduce measurement-order bias.
* Pruning: the target must return a block/hash at its own final height minus
  64800, with matching height. An unavailable/skipped height fails this exact
  specification check; no neighboring-height substitution is made.
* Archive: all archive-tagged verification blocks must be readable with matching
  heights. Archive failures do not reject a node from the ordinary pool.

The complete source spec is bundled as `near_rpc_checker/near.json`, retrieved
2026-09-11 from
https://github.com/lavanet/lava/blob/main/specs/mainnet-1/specs/near.json.
Its SHA-256 is exposed in `/status`. There is no runtime GitHub dependency.
Mainnet uses `NEAR`; testnet uses `NEART` and inherits checks by name from `NEAR`.
In this snapshot, testnet overrides chain-id to `testnet`, inherits pruning and
the shard account probes (including their `.near` suffixes), and adds an archive
probe at 42376888. **The differently named inherited archive probe at 10000000
is also retained**: testnet archive readiness requires both. The effective on-chain
Lava spec may differ from GitHub; review/update the bundled snapshot when specs
change. Passing these probes is not a full Lava provider startup/API conformance
test, nor proof of every historical state being available.

## HTTP endpoints

All checks run in the background; HTTP requests only read cached results.

| Endpoint | HTTP 200 condition |
| --- | --- |
| `/healthz` | HTTP process is alive, independent of RPC availability |
| `/readyz`, `/readyz/<node>` | Height + chain/sync status + all shard checks; independent of pruning/archive |
| `/pruning`, `/pruning/<node>` | Core readiness + pruning (complete ordinary-pool requirements) |
| `/archive`, `/archive/<node>` | Ordinary requirements + all archive checks |
| `/status`, `/status/<node>` | Always 200 for known nodes; per-check results/errors, timestamps, freshness |
| `/metrics` | Prometheus gauges for readiness, check success/freshness, latency, height and lag |

Failed/not-yet-run/expired required checks produce HTTP **503**. Unknown paths or
nodes produce **404**. Aggregate readiness requires **all** configured nodes; use
per-node endpoints for HAProxy. `/status.ready` describes core `/readyz` readiness;
archive results remain visible in `checks`.

Missing, failed, or expired pruning results only block `/pruning` and `/archive`.
Archive results only affect `/archive`. A failed/expired core check blocks all
three levels. Metrics expose `mode="readyz"`, `mode="pruning"`, and `mode="archive"`.

Every definitive failed check replaces the old result immediately, including
transport failures after retries. Unlike the EVM checker, an old success is not
preserved after an observed failure. TTL only limits the age of cached results.
Check age uses a monotonic clock and starts before the request, so slow requests
cannot refresh an old observation indefinitely. Large node lists create one
three polling threads per node (core, pruning, archive); size RPC timeouts and
polling/TTL for your deployment. Slow archive requests cannot block height/shard
polling or the pruning worker.

## Configuration

| Variable | Default / meaning |
| --- | --- |
| `NEAR_NETWORK` | `mainnet`; or `testnet` |
| `NODE_RPC_URL` | Single node, named `default` |
| `NODES_JSON` | Alternative to NODE_RPC_URL; nonempty map of names to `{ "rpc_url": "..." }` |
| `TRUSTED_RPC_URL` | `https://rpc.<network>.near.org` |
| `POLL_INTERVAL_SECONDS` | 5 seconds between polling cycles |
| `DEEP_CHECK_INTERVAL_SECONDS` | 60 seconds between pruning/archive attempts |
| `STATE_TTL_SECONDS` | 30 seconds for height/chain/shard results |
| `DEEP_STATE_TTL_SECONDS` | 180 seconds for pruning/archive; must exceed deep interval |
| `RPC_TIMEOUT_SECONDS` | 3 seconds per request |
| `RPC_RETRY_COUNT` | 2 extra attempts for transport/invalid-response failures |
| `RETRY_DELAY_SECONDS` | 0.5 seconds |
| `HTTP_HOST`, `HTTP_PORT` | `0.0.0.0`, `8080` |

An RPC JSON error is parsed as a semantic result, including HTTP 4xx JSON errors.
HTTP 429/5xx and timeouts use retries. A semantic failure is retried next cycle
(next deep interval for pruning/archive). Errors and metrics omit RPC URLs to
avoid leaking credentials. Standard HTTP(S) proxy environment settings apply.

## Run

```bash
NEAR_NETWORK=mainnet NODE_RPC_URL=http://192.0.2.10:3030 python3 -m near_rpc_checker
```

Testnet example:

```bash
NEAR_NETWORK=testnet NODE_RPC_URL=http://192.0.2.11:3030 python3 -m near_rpc_checker
```

Docker: copy `.env.example` to `.env`, set an address reachable **from the
container** (127.0.0.1 is the checker container itself), then:

```bash
docker compose up -d --build
curl -i http://127.0.0.1:8080/pruning/default
curl -i http://127.0.0.1:8080/archive/default
```

Docker liveness uses `/healthz`; configure your load balancer/Kubernetes readiness
to use `/pruning/<node>` or `/archive/<node>`. Shutdown handles SIGTERM/SIGINT.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
