#!/bin/bash
set -euo pipefail

# ==============================================================================
# Defaults
# ==============================================================================
: "${BIN:=uniond}"
: "${CHAIN_ID:=union-1}"
: "${CONFIG_PATH:=${HOME}/.union}"
: "${PUBLIC_RPC:=https://rpc.union.build:443}"
: "${NODE_API_PORT:=1317}"
: "${NODE_GRPC_PORT:=9090}"
: "${NODE_P2P_PORT:=26656}"
: "${NODE_RPC_PORT:=26657}"
: "${METRICS_PORT:=26660}"
: "${KEYRING_BACKEND:=test}"            # file|os|test
: "${INDEXER:=kv}"                      # kv|null
: "${DB_BACKEND:=goleveldb}"
: "${DIFF_HEIGHT:=1000}"
: "${LOGLEVEL:=info}"
: "${MONIKER:=rpc-node}"
: "${GENESIS_URL:=https://rpc.union.build/genesis}"
: "${WALLET:=}"
# : "${SEEDS:=}" ; : "${PEERS:=}" ; : "${ADDRBOOK_URL:=}"

# Colors
C_GRN="\e[32m"
C_RST="\e[0m"

# ==============================================================================
# Functions
# ==============================================================================
init_node() {
  printf "%b### Initialization node ###%b\n\n" "${C_GRN}" "${C_RST}"

  # Moniker / chain-id
  "${BIN}" init "${MONIKER}" --chain-id "${CHAIN_ID}" --home "${CONFIG_PATH}"

  # client.toml
  "${BIN}" config set client chain-id "${CHAIN_ID}" --home "${CONFIG_PATH}"
  "${BIN}" config set client keyring-backend "${KEYRING_BACKEND}" --home "${CONFIG_PATH}"
  "${BIN}" config set client node "http://localhost:${NODE_RPC_PORT}" --home "${CONFIG_PATH}"

  # genesis / addrbook
  if [[ -n "${ADDRBOOK_URL:-}" ]]; then
    curl -fsSL "${ADDRBOOK_URL}" -o "${CONFIG_PATH}/config/addrbook.json"
  fi

  resp="$(curl -fsSL "${GENESIS_URL}")"
  if echo "$resp" | jq -e '.result.genesis' >/dev/null 2>&1; then
    echo "$resp" | jq '.result.genesis' > "${CONFIG_PATH}/config/genesis.json"
  else
    echo "$resp" > "${CONFIG_PATH}/config/genesis.json"
  fi

  # db backend
  sed -i \
    -e "s|^db_backend =.*|db_backend = \"${DB_BACKEND}\"|" \
    "${CONFIG_PATH}/config/config.toml"

  # peers / seeds / indexer
  sed -i \
    -e "s|^indexer =.*|indexer = \"${INDEXER}\"|" \
    -e 's|^filter_peers =.*|filter_peers = "true"|' \
    -e "s|^persistent_peers =.*|persistent_peers = \"${PEERS:-}\"|" \
    -e "s|^seeds =.*|seeds = \"${SEEDS:-}\"|" \
    "${CONFIG_PATH}/config/config.toml"

  # ports / metrics
  sed -i \
    -e "s|^laddr = \"tcp://127.0.0.1:26657\"|laddr = \"tcp://0.0.0.0:${NODE_RPC_PORT}\"|" \
    -e "s|^laddr = \"tcp://0.0.0.0:26656\"|laddr = \"tcp://0.0.0.0:${NODE_P2P_PORT}\"|" \
    -e "s|^prometheus =.*|prometheus = true|" \
    -e "s|^prometheus_listen_addr =.*|prometheus_listen_addr = \":${METRICS_PORT}\"|" \
    "${CONFIG_PATH}/config/config.toml"

  # external_address
  if ext_ip="$(curl -fsS --max-time 2 https://ifconfig.me 2>/dev/null || true)"; then
    sed -i -e "s|^external_address =.*|external_address = \"${ext_ip}:${NODE_P2P_PORT}\"|" \
      "${CONFIG_PATH}/config/config.toml"
  fi

  # REST / gRPC
  sed -i \
    -e "s|^address = \"tcp://localhost:1317\"|address = \"tcp://0.0.0.0:${NODE_API_PORT}\"|" \
    -e "s|^address = \"localhost:9090\"|address = \"0.0.0.0:${NODE_GRPC_PORT}\"|" \
    "${CONFIG_PATH}/config/app.toml"

  # pruning / gas
  sed -i \
    -e 's|^pruning =.*|pruning = "custom"|' \
    -e 's|^pruning-keep-recent =.*|pruning-keep-recent = "100"|' \
    -e 's|^pruning-interval =.*|pruning-interval = "10"|' \
    -e 's|^minimum-gas-prices =.*|minimum-gas-prices = "0au"|' \
    "${CONFIG_PATH}/config/app.toml"
}

state_sync() {
  if [[ "${STATE_SYNC:-}" == "true" ]]; then
    LATEST_HEIGHT="$(curl -fsS "${PUBLIC_RPC}/block" | jq -r '.result.block.header.height')"
    SYNC_BLOCK_HEIGHT="$(( LATEST_HEIGHT - DIFF_HEIGHT ))"
    SYNC_BLOCK_HASH="$(curl -fsS "${PUBLIC_RPC}/block?height=${SYNC_BLOCK_HEIGHT}" | jq -r '.result.block_id.hash')"

    sed -i \
      -e 's|^enable =.*|enable = true|' \
      -e "s|^rpc_servers =.*|rpc_servers = \"${PUBLIC_RPC},${PUBLIC_RPC}\"|" \
      -e "s|^trust_height =.*|trust_height = ${SYNC_BLOCK_HEIGHT}|" \
      -e "s|^trust_hash =.*|trust_hash = \"${SYNC_BLOCK_HASH}\"|" \
      "${CONFIG_PATH}/config/config.toml"
  else
    sed -i \
      -e 's|^enable *=.*|enable = false|' \
      "${CONFIG_PATH}/config/config.toml"
  fi
}

create_account() {
  printf "\n%b### Create account ###%b\n" "${C_GRN}" "${C_RST}"

  if [[ "${KEYRING_BACKEND}" == "test" ]]; then
    "${BIN}" keys add "${WALLET}" --keyring-backend "${KEYRING_BACKEND}" --home "${CONFIG_PATH}"
  else
    expect -c "
      set timeout -1
      exp_internal 0
      spawn ${BIN} keys add ${WALLET} --keyring-backend ${KEYRING_BACKEND} --home ${CONFIG_PATH}
      expect \"Enter keyring passphrase*:\"
      send \"${WALLET_PASS}\n\"
      expect \"Re-enter keyring passphrase*:\"
      send \"${WALLET_PASS}\n\"
      expect eof
    "
  fi
}

set_variable() {
  source "${HOME}/.bashrc"

  if [[ -z "${ACC_ADDRESS:-}" ]]; then
    echo "export ACC_ADDRESS=$(echo "${WALLET_PASS:-}" | "${BIN}" keys show "${WALLET}" ${KEYRING_BACKEND:+--keyring-backend "${KEYRING_BACKEND}"} --home "${CONFIG_PATH}" -a)" >> "${HOME}/.bashrc"
  fi
  if [[ -z "${VAL_ADDRESS:-}" ]]; then
    echo "export VAL_ADDRESS=$(echo "${WALLET_PASS:-}" | "${BIN}" keys show "${WALLET}" ${KEYRING_BACKEND:+--keyring-backend "${KEYRING_BACKEND}"} --home "${CONFIG_PATH}" --bech val -a)" >> "${HOME}/.bashrc"
  fi
}

start_node() {
  printf "\n%b### Run Node ###%b\n\n" "${C_GRN}" "${C_RST}"
  state_sync
  exec "${BIN}" start --home "${CONFIG_PATH}" ${LOGLEVEL:+--log_level "${LOGLEVEL}"}
}

# ==============================================================================
# Main
# ==============================================================================
if [[ ! -d "${CONFIG_PATH}" ]] || [[ ! -d "${CONFIG_PATH}/config" || "$(ls -la "${CONFIG_PATH}/config" | grep -cie '.*key\.json')" -eq 0 ]]; then
  init_node
fi

if [[ -n "${WALLET}" ]]; then
  if ! "${BIN}" keys show "${WALLET}" ${KEYRING_BACKEND:+--keyring-backend "${KEYRING_BACKEND}"} --home "${CONFIG_PATH}" >/dev/null 2>&1; then
    create_account
  fi
  set_variable
fi

start_node
