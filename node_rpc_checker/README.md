# node-rpc-checker

The only version source is `node_rpc_checker/VERSION` (print it with
`python3 tools/release.py version` from the checker directory). Images use `svetekllc/node-rpc-checker:<version>`.
The version is used by package metadata and
RPC User-Agent, and exposed in `/healthz`, `/status` and readiness responses.
The Docker build checks its VERSION label against both installed package metadata
and the module version. The current source revision is not automatically published.

Universal NEAR/EVM RPC readiness service driven by bundled Lava specifications.
Python 3.11+, no third-party runtime dependencies. One chain per service instance,
multiple named nodes per instance. Use separate instances for separate chains.

## Layout and launch

- `node_rpc_checker/`: Python package, engine, adapters, HTTP/WS transports.
- `node_rpc_checker/specs/`: bundled near.json, ethereum.json, base.json, arbitrum.json.
- `tests/`: unit and local HTTP/WS integration tests.
- `legacy/near`, `legacy/evm_checker`: preserved standalone implementations.

Run from this directory:

```bash
CHAIN_ID=BASE NODE_RPC_URL=http://192.0.2.10:8545 python3 -m node_rpc_checker
CHAIN_ID=NEAR NODE_RPC_URL=http://192.0.2.11:3030 python3 -m node_rpc_checker
```

Docker: copy `.env.example` to `.env`, configure reachable upstream addresses,
then run `python3 tools/release.py compose up -d --build`. Container localhost means the container,
not the host. Compose binds the monitoring API to host loopback by default.
From the repository root:

```bash
python3 node_rpc_checker/tools/release.py build
```

The wrapper derives the Docker tag and Compose build-arg from VERSION; no manual
version literals are needed in Compose. Direct Compose requires CHECKER_VERSION;
use the wrapper to avoid mismatches. Edit VERSION before creating a new release.
The wrapper does not publish images. Raw Docker builds must explicitly provide
`--build-arg VERSION=<matching version>` and an appropriate tag.

Docker builds a wheel in a separate builder stage and installs it without network
access in the runtime stage. Runtime starts the installed `node-rpc-checker`
console script from `/app`, not a source checkout. `python -m node_rpc_checker`
and `node-rpc-checker --version` are supported. The wheel includes VERSION, all
four spec snapshots, metadata, README description and a copy of the repository
LICENSE. Python 3.12 in Docker is one supported runtime, not the minimum version.

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
Missing `chain-id` verification is a configuration error (exit code 2).
`GET_BLOCK_BY_NUM` templates require exactly one `%d` or `%x`; other height and
verification templates cannot contain placeholders. Formatting and the resulting
JSON are validated before polling starts, including selected addon rules.
Hex values are validated; NEAR hashes remain opaque despite
the spec's base64 annotation. This service does not build Lava finalization proofs.

NEART inherits the named archive probe at 10000000 and adds 42376888: both are
required for archive with this snapshot. Shard account names keep their .near
suffixes exactly as supplied by the spec.

## Readiness endpoints

| Endpoint (also accepts /<node>) | Required successful, fresh checks |
| --- | --- |
| /readyz | Core rules + trusted height − target height <= MAX_BEHIND_BLOCKS |
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
- The trusted chain is verified before refreshing reference height, including NEAR
  syncing status. Target height is read after obtaining that snapshot.
  `MAX_BEHIND_BLOCKS` sets the inclusive allowed lag (default **0**).
  With `MAX_BEHIND_BLOCKS=10`, lag of 10 passes and lag of 11 fails; equal/ahead
  heights pass. This applies to NEAR/EVM, HTTP/WS and all readiness levels.
  It is one setting per service instance and is not inferred from Lava QoS fields.
  Network, shards, freshness, pruning and archive conditions remain required.

Core, pruning and archive have separate globally bounded worker pools. Slow archive
requests do not block core polling. HTTP health requests only inspect cached
state. Explicit failures replace old success immediately, including transport
failures after retries. TTL uses monotonic age from the start of an attempt.
Checks are interleaved across nodes and run concurrently up to each pool's limit.
A slow check does not impose a barrier on the whole group; saturated pools can
still delay other nodes. Expired results fail closed instead of pretending to be fresh.

All nodes and transports in one service instance share a single-flight trusted
snapshot. `TRUSTED_STATE_TTL_SECONDS` (default 30, maximum STATE_TTL_SECONDS) bounds
its age from refresh start. A dedicated updater waits `TRUSTED_REFRESH_INTERVAL_SECONDS`
(default 5, strictly below trusted TTL) between completed refreshes, independently
of node polling. During refresh, readers use the previous snapshot only while
it is still fresh, without waiting for the refresh lock. At most one refresh runs at a time; successful EVM
refreshes require two RPC calls regardless of node count. A failed refresh preserves
the previous successful height for the lifetime of the process, even after TTL expiry.
On-demand callers without a fresh snapshot retain TTL-length backoff from failure
completion to prevent retry storms. The single proactive updater bypasses that
backoff and retries after its configured refresh interval, not after the TTL.
After bootstrap, target checks do not initiate expired-reference refreshes;
the independent updater owns retries. No stale reference enforces the lag limit. Status reads never
perform RPC I/O or wait for a refresh. Replicas do not share this cache.
Each cached height comparison retains the expiry of the particular snapshot it
used; publishing a newer reference cannot extend an old comparison's lifetime.

Migration: explicitly configured `TRUSTED_STATE_TTL_SECONDS=5` is not replaced
by the new default. Set it to 30 (with STATE_TTL_SECONDS at least 30), or choose
a shorter refresh interval and a deliberate smaller freshness budget. Equal
refresh interval and TTL now fail configuration validation at startup.

The height comparison, including the configured lag allowance, uses this bounded-age snapshot, not a fresh
public RPC call per target. Expiry marks comparisons as unverified without
failing an otherwise healthy target. Choose a TTL that allows the reference
network/height requests to finish so lag validation can remain active.
Trusted RPC uses a separate client with `TRUSTED_RPC_TIMEOUT_SECONDS=5`;
target HTTP/WS and subscriptions keep `RPC_TIMEOUT_SECONDS=3`. The role, not
URL equality, selects the timeout (even if target and trusted URLs are identical).
The nominal two-call retry budget at defaults is 32 seconds, versus the 30-second
freshness bound, so startup warns about insufficient retry margin. Fast successful
requests still pass. To accommodate the nominal budget plus refresh interval,
increase both trusted and state TTLs above 37 seconds, for example to 45; this
also changes the accepted data age and should be an explicit operator decision.
This is not a hard end-to-end deadline: HTTP timeouts do not bound
all DNS/header/body work together. Allow for the previous fetch duration, the refresh
interval and the next fetch duration to avoid expiry during consecutive slow refreshes.
Sustained slow or failed trusted RPCs disable fresh lag validation, not target readiness.
Startup warns if TTL does not exceed one nominal fetch
budget plus the refresh interval; this warning is not a hard timing guarantee.

### Protection during trusted outages

Trusted is advisory: `/readyz`, `/pruning` and `/archive` do not fail solely
because it is unavailable. There is no reference-outage admission deadline.
`REFERENCE_GRACE_SECONDS` is deprecated and accepted only for config compatibility;
it no longer controls admission, including when set to zero.

With a healthy, fresh trusted observation, `MAX_BEHIND_BLOCKS` is enforced.
Otherwise the latest successful trusted height is retained in memory and
`delta_blocks = last_trusted_height - current_target_height` continues updating.
The delta becomes more negative as the target advances; it is diagnostic only,
not proof of current network synchronization. On cold start without any successful
trusted observation, trusted height and delta are absent, never fabricated as zero.
Restart clears the remembered height; it is not persisted to disk.

Core, network, shard, WS and requested historical checks must still succeed and
remain fresh. Height regression fails the check. While trusted comparison is
unavailable, each target transport must show forward progress within
`NODE_PROGRESS_TTL_SECONDS` (default 30). A successful local probe recovers a
target independently of trusted. Cold-start targets can pass their own checks.
There is no guarantee of bounded lag until trusted recovers and a new target
comparison succeeds. Recovery alone does not produce an intermediate 503.

`/status` exposes `reference_fresh=false` and `reference_error` on unverified
height results, plus per-node `degraded` and top-level reference diagnostics.
`node_rpc_checker_degraded{node,mode}` identifies available but unverified modes.
`node_rpc_checker_reference_up` reports failed/expired trusted observations;
`reference_age_seconds` shows the age of the last successful observation.
`node_rpc_checker_rpc_up{chain,node,role,transport}` reports endpoint probe availability.
Backend samples use the configured node name and role `backend`; trusted uses
an empty node name and role `trusted`. Transports are `http` or `ws` (including TLS variants).
All exported families use `node_rpc_checker_`; old aliases are no longer emitted.
Update dashboards and alerts from `evm_height_checker_rpc_up` to
`node_rpc_checker_rpc_up`, also replacing the old URL-based aggregation.
For the Kubernetes scrape configuration that renames the RPC `node` label to `exported_node`:

```promql
max by (app_kubernetes_io_instance, exported_node, role, transport) (
  node_rpc_checker_rpc_up{
    namespace="haproxy", app_kubernetes_io_instance=~"${chain:regex}"
  }
)
```

A reachable but lagging target has rpc_up=1 and readiness=0.
Full endpoint URLs cannot be exported. Existing `by (endpoint)` dashboards
must use safe identity labels; address tables use origins without paths or queries.
Reference selection/failover is still an operator action, not automatic.

`cycle()` is a one-shot executor, not a scheduler. Production core, pruning and
archive loops all use `run_mode()`, one scheduler per mode for all nodes.
Each check is rescheduled after its own completion plus its mode's interval;
overlapping attempts of the same check and unbounded executor queues are forbidden.
Core uses CHECK_WORKERS globally; pruning and archive each use DEEP_CHECK_WORKERS.
Migration: CHECK_WORKERS no longer multiplies by node count. Large fleets may
need higher worker limits to complete checks within their state TTLs.
After loading the actual spec-driven plans, startup estimates capacity separately
for core, pruning and archive: `ceil(jobs / workers) * RPC_TIMEOUT_SECONDS`.
If that nominal round plus the mode's interval reaches its TTL, a warning reports
the mode, task count, worker count, nominal round, interval and TTL. Counts include
configured transports, subscriptions and addons. Neither worker limits nor TTLs
are changed automatically and the configuration is not rejected.
This is a conservative scheduling heuristic assuming one target timeout per task,
not an upper bound or a throughput guarantee: retries, multi-call WS checks,
trusted waits, host load and latency distributions can change actual durations.
Absence of a warning is not proof of sufficient capacity. Increasing state TTLs
accepts older results and may also require deliberate reference-policy changes.
Shutdown skips queued checks; in-flight transport calls remain timeout-bounded
subject to the DNS/header limitations below.

Trusted refresh frequency remains explicitly independent of polling. For rare
polling, increase TRUSTED_REFRESH_INTERVAL_SECONDS together with trusted/state
TTLs and POLL_INTERVAL_SECONDS, allowing request/queue time as well. Changing
only poll to 300 seconds with a 30-second TTL cannot preserve continuous readiness.
Refreshes are not silently skipped based on demand, because cached readiness also
depends on reference freshness. Each instance performs about two RPC calls per
successful refresh; replicas multiply this traffic.

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

The EVM adapter obtains method names from SUBSCRIBE/UNSUBSCRIBE directives and
supplies `newHeads`. It validates both directives at startup for WS nodes.
UNSUBSCRIBE must contain a single `params: ["%s"]` slot; the returned subscription
ID is inserted into the parsed JSON structure, never interpolated as JSON text.
Unsupported SUBSCRIBE templates fail startup rather than being ignored.

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
| POLL_INTERVAL_SECONDS | 5 seconds after each core check completes |
| DEEP_CHECK_INTERVAL_SECONDS | 60 seconds after each deep check completes |
| STATE_TTL_SECONDS | 30 seconds for core |
| MAX_BEHIND_BLOCKS | 0; nonnegative integer, inclusive lag allowance |
| TRUSTED_STATE_TTL_SECONDS | 30 seconds; must not exceed STATE_TTL_SECONDS |
| TRUSTED_REFRESH_INTERVAL_SECONDS | 5 seconds between refreshes; must be below trusted TTL |
| REFERENCE_GRACE_SECONDS | Deprecated; accepted for compatibility, no effect on admission |
| NODE_PROGRESS_TTL_SECONDS | 30 seconds since last observed forward height progress |
| DEEP_STATE_TTL_SECONDS | 180 seconds, must exceed deep interval |
| RPC_TIMEOUT_SECONDS | 3 seconds |
| TRUSTED_RPC_TIMEOUT_SECONDS | 5 seconds; trusted network/height calls only, including HTTP body reads |
| RPC_RETRY_COUNT | 2 extra attempts for transport/invalid-envelope errors; range 0–5 |
| CHECK_WORKERS | 4 concurrent core checks globally; range 1–32 |
| DEEP_CHECK_WORKERS | 2 workers in each of the separate pruning/archive pools; range 1–32 |
| RETRY_DELAY_SECONDS | 0.5 seconds |
| HTTP_HOST / HTTP_PORT | 0.0.0.0 / 8080 |

NEAR HTTP 4xx JSON errors are parsed to preserve UNKNOWN_ACCOUNT.
HTTP 429/5xx and transport failures are retried. Semantic failures are retried
next scheduled cycle. Subscription is attempted once per core cycle.
Tune intervals/timeouts/TTLs for upstream latency and quotas; WS/addons multiply
request counts. EVM eth_syncing is not a rule in these supplied specs.

Metrics prefix: node_rpc_checker_, with chain/node and mode or check labels.
Metrics include readiness, check success/freshness, latency, timestamps and HTTP
height/delta. Full RPC URLs are excluded from errors and, by default, metrics;
endpoint info exposes only origins (scheme, host/IP and explicit port).
There is no option to expose full URLs in metric labels.
Reference metrics are instance-wide (chain label only): reference_cache_fresh, reference_up,
reference_refresh_attempts_total and reference_refresh_failures_total are present
from startup. They count actual fetch attempts, not cached failures or cache hits,
and include on-demand and proactive work. reference_age_seconds is absent before
the first successful snapshot; reference_refresh_duration_seconds is absent before
the first completed attempt. Both are in seconds, including retry time where applicable.
`reference_cache_fresh` describes cached observation freshness only. `reference_up`
additionally requires that the latest refresh did not fail. Thus a failed refresh
can yield reference_cache_fresh=1 and reference_up=0 until the cached observation expires.
Use reference_up=0 to alert on trusted unavailability independently of target readiness.
All exported families include HELP and TYPE metadata. Tests require explicit descriptions for emitted
families. If a description is accidentally missing at runtime, a generic HELP
preserves all samples and records one internal `monitoring/metric_help` error per
missing family per process, without repeated scrape log spam. The error counter
is visible on the following scrape.
`check_duration_seconds` measures whole-check duration. Height probes with timing
details additionally expose `target_rpc_duration_seconds` (including target retries)
and `reference_wait_duration_seconds` (including any reference refresh/lock wait).
Durations retain millisecond resolution but are exported in seconds.
Use target RPC timing, not whole-check duration, to compare node latency.
The configured lag limit is exposed in status/readiness responses and in
`node_rpc_checker_max_behind_blocks`; `delta_blocks` retains its signed value
(trusted minus target), including a positive delta accepted within the limit.

Expected RPC failures have `error_kind=rpc_error`. Unexpected exceptions have
`error_kind=internal_error` and increment `node_rpc_checker_internal_errors_total`
per node/check, including fixed service and monitoring operations (poll loop,
trusted updater, HTTP response/handler, listen and lifecycle). Logs include sanitized stack locations and exception type, but
omit exception values, source lines, chained exceptions and frame locals.
Also alert on failed metric scrapes and process exits/restarts: a broken metrics
endpoint or a process that cannot start cannot expose its own error counters.
Target/internal failures fail readiness; reference failures follow the protection
policy above. Internal error counters survive recovery
until the service restarts. Invalid shared-reference state marks height comparisons
as unverified (`reference_fresh=false`) without turning target success into failure.

### Metric contract and migration

All names below have the prefix `node_rpc_checker_`. There are 28 canonical
families, with no deprecated metric aliases. Some samples
appear only after a matching observation or error; absent does not mean zero.

| Canonical family | Meaning |
| --- | --- |
| rpc_up | Fresh successful RPC height probe; independent of readiness and lag |
| ready | Admission for readyz, pruning or archive |
| degraded | Mode is available without a fresh verified height comparison |
| height_comparison_verified | Latest height comparison passed, and both local result and reference used remain fresh |
| check_ok | Individual check result, including current progress guard |
| check_fresh | Individual check result is within local TTL |
| node_height | Last measured HTTP target height |
| trusted_height | Trusted height used by the latest HTTP diagnostic, possibly stale |
| delta_blocks | Known trusted minus measured target height; signed, absent if reference unknown |
| max_behind_blocks | Configured inclusive lag allowance |
| check_duration_seconds | Last completed check duration |
| target_rpc_duration_seconds | Last target height RPC duration, when recorded |
| reference_wait_duration_seconds | Reference acquisition duration, when recorded |
| check_last_completed_timestamp_seconds | Unix timestamp of check completion, success or failure |
| reference_cache_fresh | Last successful reference observation is within TTL |
| reference_up | Cached reference is fresh and latest refresh did not fail |
| reference_age_seconds | Age since the start of the last successful reference fetch |
| reference_refresh_duration_seconds | Last completed reference fetch duration |
| reference_refresh_attempts_total | Actual reference fetch attempts |
| reference_refresh_failures_total | Failed reference fetch attempts |
| check_results_total | Completed check attempts by outcome and error_kind |
| internal_errors_total | Internal errors by configured node/check or fixed service operation |
| node_endpoints_info | Backend HTTP/WS origins by node, including unavailable nodes |
| node_type_info | Detected backend storage type (`prune` or `archive`) from fresh successful HTTP deep checks; absent when neither type is currently proven |
| rpc_endpoint_info | RPC origin by node, role and transport, including trusted |
| check_consecutive_failures | Consecutive failed completed attempts of each check |
| check_last_success_timestamp_seconds | Last successful completion of each check, or zero before first success |
| rpc_last_error_timestamp_seconds | Last failed target check per transport or failed trusted refresh, or zero before first failure |

Endpoint info is configuration metadata, emitted before any successful probe.
Only the origin (scheme, hostname/IP and optional explicit port) is exposed;
userinfo, path, query and fragment are omitted. Origins reveal infrastructure
addresses but not path/query tokens. Full URL exposure is not supported.
Endpoints sharing an origin remain distinct through node/role/transport.

Check history uses labels chain/node/check/mode. A successful completed check
resets its consecutive failures; a sibling's success does not reset it. An
unverified target height during trusted outage is still a target success. Last
success persists through failures; last error persists through recovery. History
is in memory and resets on restart. Status/metrics reads and TTL expiry do not
create error events. All failed target checks, including historical verification
or internal errors, update their transport's last-error timestamp; this is not
solely a network-connection error indicator.

The Grafana **Node Endpoints** table displays the maximum failure streak among
core checks and replicas, not a count of failed polling rounds. Time Since Success
uses the oldest last-success timestamp across core checks and replicas; any zero
means a required check has never succeeded. Deep pruning/archive checks are
excluded from these aggregates. Chain and node form the table join key to avoid
collisions across chains.

**RPC Last Error** shows the last observed error in the selected range, joined
with safe origin metadata. Zero means "None in selected range", not proof of
uninterrupted availability: errors between scrapes or before restarts can be
missed. Trusted errors are independent of backend history.

`height_comparison_verified{chain,node,transport}` starts at zero and remains zero
on cold start, reference outage, stale results, or failed/lagging comparisons.
A negative delta against a stale cached height is not a verified comparison.

`check_results_total{chain,node,check,outcome,error_kind}` increments once at check
completion. Allowed pairs are success/none, failure/rpc_error,
failure/internal_error, and unverified/reference_error. The last pair means that
the target height was obtained but could not be compared to a fresh reference;
it does not by itself make readiness fail. Status/metrics reads and later TTL
expiry do not increment counters. Counter series appear on their first event and
reset on restart. Error messages and URLs are never counter labels.

| Removed name | Replacement |
| --- | --- |
| reference_valid | reference_cache_fresh |
| latency_ms | check_duration_seconds (old value / 1000) |
| target_rpc_latency_ms | target_rpc_duration_seconds (old value / 1000) |
| trusted_wait_ms | reference_wait_duration_seconds (old value / 1000) |
| last_attempt_timestamp | check_last_completed_timestamp_seconds |

Old names are no longer exported, including HELP/TYPE metadata. Update dashboards
and alerts to the replacements together with the service rollout. Do not keep
fallback queries referencing removed names. Per-check JSON status fields remain
unchanged; reference diagnostics use reference_cache_fresh instead of reference_valid.

## Security and operational limits

- Configuration is operator-trusted. RPC URLs cannot be supplied by incoming
  health requests. Private upstream IPs are intentionally allowed; restrict
  egress with firewall/network policy to approved RPCs and trusted DNS/proxies.
- HTTP redirects are rejected. URLs reject userinfo, whitespace/control
  characters, invalid ports and fragments. Percent-encode path/query tokens;
  protect the environment file and prefer HTTPS/WSS for credentials.
- Full URL labels are prohibited; endpoint info reveals only scheme, host and port.
  Previously scraped secrets remain subject to storage retention; removing
  the label does not erase history. Rotate any exposed credentials as appropriate.
- JSON-RPC IDs must match both type and value. HTTP responses are capped at
  4 MiB, WS messages at 1 MiB. Upstream error names are length/character bounded.
  HTTP body reads have an elapsed-time guard; DNS, connect and HTTP header
  processing do not have a hard end-to-end deadline. Use a trusted egress proxy
  with total-request deadlines when checking hostile endpoints.
- The monitoring server allows at most 32 active handlers and a 5-second socket
  inactivity timeout; excess connections are closed. It has no authentication
  or TLS: keep Compose's loopback binding, or use a protected reverse proxy.
  Do not expose the stdlib monitoring server directly to the public internet.
- Up to 64 configured nodes, names up to 64 characters. Four background loops
  (three mode schedulers and one reference updater), plus at most CHECK_WORKERS
  + 2 * DEEP_CHECK_WORKERS worker threads: 12 background threads at defaults,
  independent of node count. Main/HTTP request threads are additional.
  This bounds resources, not latency or throughput: size worker limits and TTLs
  to real upstream latency and quotas. A pool whose workers are all blocked
  cannot service another check until a worker returns.
- These changes and regression tests are a code review, not a penetration test
  or a guarantee that a remote node is honest. Archive probes establish only
  the historical availability covered by the Lava specification.

## Migration and tests

The unified service was renamed from `rpc-checker` / `rpc_checker` to
`node-rpc-checker` / `node_rpc_checker`. The project directory and Python
package are both `node_rpc_checker`; launch with `python3 -m node_rpc_checker`.
Update build contexts, imports, deployment image references and Compose service
names. Prometheus queries using `rpc_checker_*` must use `node_rpc_checker_*`.
No compatibility alias or duplicate metrics are provided. Endpoint paths and
environment variables are unchanged. Legacy implementations keep their names.

Old implementations/configs are retained in legacy/ and excluded from the new
image/package. Image/module now: node-rpc-checker / python3 -m node_rpc_checker.
NEAR_NETWORK becomes CHAIN_ID=NEAR or NEART; EVM needs its explicit spec ID.
Metrics change from near_rpc_checker_* or evm_height_checker_* to node_rpc_checker_*.
Update dashboards/alerts separately; the old EVM Grafana dashboard remains
unchanged for legacy deployments. HTTP paths remain; EVM readiness now requires
spec checks, not just height/WS upgrade. Unlike legacy EVM, known failures
immediately invalidate readiness rather than preserving old success.

No services, HAProxy configurations or Kubernetes resources are deployed/changed
by this repository migration.

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests -t . -v
```

Development tools (not runtime dependencies):

```bash
python3 -m pip install -e '.[dev]'
ruff check node_rpc_checker tests tools
ruff format --check node_rpc_checker tests tools
mypy
python3 -m build
```

GitHub Actions runs these checks and unit/local-transport tests on Python 3.11
and 3.12. Mypy checks annotated code and untyped function bodies; this is not
strict end-to-end typing of all dynamic JSON. Legacy implementations are excluded
from formatting and the checker quality workflow.
CI builds sdist/wheel and smoke-tests the wheel in a clean virtual environment
outside the source tree. Tests also exercise real SIGTERM/SIGINT shutdown,
multinode configuration, WS fragmentation/close/size limits and monitoring 500s.
Internal monitoring response failures return a generic 500 with sanitized logs;
client disconnects during writes do not trigger a second response.
