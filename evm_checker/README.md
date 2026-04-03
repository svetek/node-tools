# evm-height-checker

`evm-height-checker` compares the block height of a local EVM node with a remote RPC endpoint and reports whether the lag stays within the allowed threshold.

Core behavior:

- requests `eth_blockNumber` from both local and remote RPC endpoints;
- calculates the delta as `remote - local`;
- marks the check as `healthy` when `delta <= MAX_BEHIND_BLOCKS`;
- treats the local node as healthy when it is equal to or ahead of the remote node.

The service is built for production use:

- no external Python dependencies are required;
- RPC timeouts and retries are supported;
- short RPC failures do not immediately drop readiness while the last successful state is still within TTL;
- exposes `healthz`, `readyz`, `status`, and Prometheus metrics at `/metrics`;
- shuts down gracefully on `SIGTERM`;
- runs in Docker without extra runtime dependencies inside the container.

## Local Run

```bash
cp .env.example .env
export $(grep -v '^#' .env | xargs)
python3 -m evm_height_checker
```

## Docker

Create a runtime env file first:

```bash
cp .env.example .env
```

Build the image:

```bash
docker build -t evm-height-checker:latest .
```

Run the container:

```bash
docker run -d \
  --name evm-height-checker \
  --restart unless-stopped \
  --env-file ./.env \
  -p 8080:8080 \
  evm-height-checker:latest
```

## Docker Compose

Start the service:

```bash
cp .env.example .env
docker compose up -d --build
```

Stop the service:

```bash
docker compose down
```

After startup:

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
curl http://127.0.0.1:8080/status
curl http://127.0.0.1:8080/metrics
```

## Environment Variables

Required:

- `LOCAL_RPC_URL` - local EVM node RPC endpoint.
- `REMOTE_RPC_URL` - remote RPC endpoint used for comparison.

Optional:

- `MAX_BEHIND_BLOCKS` - maximum allowed lag of the local node in blocks. Default: `0`.
- `RPC_USER_AGENT` - HTTP `User-Agent` used for RPC requests. Default: `evm-height-checker/0.1`. Useful because some public RPC providers reject requests without this header.
- `POLL_INTERVAL_SECONDS` - polling interval. Default: `5`.
- `RPC_TIMEOUT_SECONDS` - timeout for a single RPC request. Default: `3`.
- `RPC_RETRY_COUNT` - number of retries after the initial failed attempt. Default: `2`.
- `RETRY_DELAY_SECONDS` - delay between retries. Default: `0.5`.
- `STATE_TTL_SECONDS` - how long the last successful state remains valid for readiness. Default: `max(POLL_INTERVAL_SECONDS * 3, 30)`.
- `HTTP_HOST` - HTTP server bind address. Default: `0.0.0.0`.
- `HTTP_PORT` - HTTP server port. Default: `8080`.

## HTTP Endpoints

- `GET /healthz` - process liveness endpoint.
- `GET /readyz` - readiness endpoint. Returns success only when the service has a fresh successful comparison and the local node is not behind the threshold.
- `GET /status` - detailed JSON status with timestamps, errors, the last comparison result, and per-endpoint RPC state.
- `GET /metrics` - Prometheus metrics endpoint.

## Prometheus Metrics

All exported metrics are `gauge` metrics.

- `evm_height_checker_local_height` - latest block height returned by the local RPC endpoint.
- `evm_height_checker_remote_height` - latest block height returned by the remote RPC endpoint.
- `evm_height_checker_rpc_up{endpoint="..."}` - RPC endpoint availability with the endpoint URL exposed as a Prometheus label.
- `evm_height_checker_delta_blocks` - block delta calculated as `remote - local`. Negative values mean the local node is ahead of the remote endpoint.
- `evm_height_checker_healthy` - result of the last successful comparison. `1` means healthy, `0` means unhealthy.
- `evm_height_checker_ready` - current readiness state with TTL applied. `1` means ready, `0` means not ready.
- `evm_height_checker_consecutive_failures` - number of failed checks in a row.
- `evm_height_checker_last_success_timestamp` - Unix timestamp of the last successful check.
- `evm_height_checker_last_attempt_timestamp` - Unix timestamp of the last check attempt, successful or failed.
- `evm_height_checker_rpc_last_success_timestamp{endpoint="..."}` - Unix timestamp of the last successful RPC call with the endpoint URL exposed as a label.
- `evm_height_checker_rpc_last_error_timestamp{endpoint="..."}` - Unix timestamp of the last failed RPC call with the endpoint URL exposed as a label.

When one endpoint is down, `evm_height_checker_delta_blocks` keeps the last successful comparison value, while the `*_rpc_up` and `*_rpc_last_error_timestamp` metrics show which endpoint is currently failing.

Example:

```text
# HELP evm_height_checker_local_height Latest local node block height.
# TYPE evm_height_checker_local_height gauge
evm_height_checker_local_height 448706644
# HELP evm_height_checker_remote_height Latest remote node block height.
# TYPE evm_height_checker_remote_height gauge
evm_height_checker_remote_height 448706642
# HELP evm_height_checker_delta_blocks Remote height minus local height.
# TYPE evm_height_checker_delta_blocks gauge
evm_height_checker_delta_blocks -2
# HELP evm_height_checker_healthy Last successful comparison status.
# TYPE evm_height_checker_healthy gauge
evm_height_checker_healthy 1
# HELP evm_height_checker_ready Current readiness status with TTL applied.
# TYPE evm_height_checker_ready gauge
evm_height_checker_ready 1
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```
