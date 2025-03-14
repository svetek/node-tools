#!/bin/bash

[[ -z $CHAIN_ID ]] && CHAIN_ID="celestia"
[[ -z $PUBLIC_RPC ]] && PUBLIC_RPC="https://rpc.cosmos.directory/celestia:443"
[[ -z $NODE_API_PORT ]] && NODE_API_PORT="1317"
[[ -z $NODE_GRPC_PORT ]] && NODE_GRPC_PORT="9090"
[[ -z $NODE_P2P_PORT ]] && NODE_P2P_PORT="26656"
[[ -z $NODE_RPC_PORT ]] && NODE_RPC_PORT="26657"
[[ -z $NODE_JRPC_PORT ]] && NODE_JRPC_PORT="26658"

case ${NODE_TYPE,,} in
  "app")
    [[ -z $CONFIG_PATH ]] && CONFIG_PATH="/root/.celestia-app"
    ;;
  "node")
    [[ -z $CONFIG_PATH ]] && CONFIG_PATH="/root/.celestia-light"
    ;;
esac

init_node() {
  echo -e "\e[32m### Initialization node ###\e[0m\n"

  case ${NODE_TYPE,,} in
    "app")
      # Set moniker and chain-id for Celestia (Moniker can be anything, chain-id must be an integer)
      $BIN init ${MONIKER:?Moniker is not set. You need to set up a value for the MONIKER variable.} --chain-id $CHAIN_ID --home $CONFIG_PATH

      # Set keyring-backend and chain-id configuration
      $BIN config chain-id $CHAIN_ID --home $CONFIG_PATH
      $BIN config keyring-backend $KEYRING_BACKEND --home $CONFIG_PATH
      $BIN config node http://localhost:$NODE_RPC_PORT --home $CONFIG_PATH

      # Download addrbook and genesis files
      [[ -n $ADDRBOOK_URL ]] && wget -O $CONFIG_PATH/config/addrbook.json $ADDRBOOK_URL

      wget -O $CONFIG_PATH/config/genesis.json ${GENESIS_URL:-https://raw.githubusercontent.com/celestiaorg/networks/master/celestia/genesis.json}

      sed -i \
        -e 's|^broadcast-mode =.*|broadcast-mode = "sync"|' \
        $CONFIG_PATH/config/client.toml

      sed -i \
        -e "s|^db_backend =.*|db_backend = \"${DB_BACKEND:-goleveldb}\"|" \
        $CONFIG_PATH/config/config.toml

      # Set seeds/peers
      sed -i \
        -e 's|^indexer =.*|indexer = "null"|' \
        -e 's|^filter_peers =.*|filter_peers = "true"|' \
        -e "s|^persistent_peers =.*|persistent_peers = \"$PEERS\"|" \
        -e "s|^seeds =.*|seeds = \"$SEEDS\"|" \
        $CONFIG_PATH/config/config.toml

      # Set timeout
      sed -i \
        -e 's|^timeout_propose =.*|timeout_propose = "10s"|' \
        -e 's|^timeout_propose_delta =.*|timeout_propose_delta = "500ms"|' \
        -e 's|^timeout_prevote =.*|timeout_prevote = "1s"|' \
        -e 's|^timeout_prevote_delta =.*|timeout_prevote_delta = "500ms"|' \
        -e 's|^timeout_precommit =.*|timeout_precommit = "1s"|' \
        -e 's|^timeout_precommit_delta =.*|timeout_precommit_delta = "500ms"|' \
        -e 's|^timeout_commit =.*|timeout_commit = "11s"|' \
        -e 's|^create_empty_blocks =.*|create_empty_blocks = true|' \
        -e 's|^create_empty_blocks_interval =.*|create_empty_blocks_interval = "0s"|' \
        -e 's|^timeout_broadcast_tx_commit =.*|timeout_broadcast_tx_commit = "50s"|' \
        -e 's|^skip_timeout_commit =.*|skip_timeout_commit = false|' \
        $CONFIG_PATH/config/config.toml

      # Set ports
      sed -i \
        -e "s|^laddr = \"tcp://127.0.0.1:26657\"|laddr = \"tcp://0.0.0.0:$NODE_RPC_PORT\"|" \
        -e "s|^laddr = \"tcp://0.0.0.0:26656\"|laddr = \"tcp://0.0.0.0:$NODE_P2P_PORT\"|" \
        -e "s|^external_address *=.*|external_address = \"$(wget -qO- eth0.me):$NODE_P2P_PORT\"|" \
        -e "s|^prometheus =.*|prometheus = true|" \
        -e "s|^prometheus_listen_addr =.*|prometheus_listen_addr = \":${METRICS_PORT:-26660}\"|" \
        $CONFIG_PATH/config/config.toml

      sed -i \
        -e "s|^address = \"tcp://0.0.0.0:1317\"|address = \"tcp://0.0.0.0:$NODE_API_PORT\"|" \
        -e "s|^address = \"0.0.0.0:9090\"|address = \"0.0.0.0:$NODE_GRPC_PORT\"|" \
        $CONFIG_PATH/config/app.toml

      # Config pruning, snapshots and min price for GAZ
      sed -i \
        -e 's|^snapshot-interval =.*|snapshot-interval = 0|' \
        -e 's|^pruning =.*|pruning = "custom"|' \
        -e 's|^pruning-keep-recent =.*|pruning-keep-recent = "100"|' \
        -e 's|^pruning-interval =.*|pruning-interval = "10"|' \
        -e 's|^minimum-gas-prices =.*|minimum-gas-prices = "0.002utia"|' \
        $CONFIG_PATH/config/app.toml
      ;;

    "node")
      args=(
        "${CHAIN_ID:+--p2p.network $CHAIN_ID}" \
        "${CONFIG_PATH:+--node.store $CONFIG_PATH}" \
        "${CORE_IP:+--core.ip $CORE_IP}" \
        "${CORE_GRPC_PORT:+--core.port $CORE_GRPC_PORT}" \
        "${KEYRING_BACKEND:+--keyring.backend $KEYRING_BACKEND}" \
        "${METRICS_ENDPOINT:+--metrics}" \
        "${METRICS_ENDPOINT:+--metrics.endpoint $METRICS_ENDPOINT}" \
        "${NODE_JRPC_PORT:+--rpc.port $NODE_JRPC_PORT}" \
        "${RPC_SKIP_AUTH:+--rpc.skip-auth}" \
        "${WALLET:+--keyring.keyname $WALLET}" \
        "--rpc.addr 0.0.0.0" \
        )
      if [ "$KEYRING_BACKEND" = "test" ]; then
        $BIN light init ${args[@]}
      else
        echo -e "$WALLET_PASS\n$WALLET_PASS" | $BIN light init ${args[@]}
      fi

      ;;
  esac
}

state_sync() {
  if [[ $STATE_SYNC && $STATE_SYNC == "true" ]]
  then
    LATEST_HEIGHT=$(curl -s $PUBLIC_RPC/block | jq -r .result.block.header.height)
    SYNC_BLOCK_HEIGHT=$(($LATEST_HEIGHT - ${DIFF_HEIGHT:-1000}))
    SYNC_BLOCK_HASH=$(curl -s "$PUBLIC_RPC/block?height=$SYNC_BLOCK_HEIGHT" | jq -r .result.block_id.hash)
    sed -i \
      -e 's|^enable =.*|enable = true|' \
      -e "s|^rpc_servers =.*|rpc_servers = \"$PUBLIC_RPC,$PUBLIC_RPC\"|" \
      -e "s|^trust_height =.*|trust_height = $SYNC_BLOCK_HEIGHT|" \
      -e "s|^trust_hash =.*|trust_hash = \"$SYNC_BLOCK_HASH\"|" \
      $CONFIG_PATH/config/config.toml
  else
    sed -i \
      -e 's|^enable *=.*|enable = false|' \
      $CONFIG_PATH/config/config.toml
  fi
}

create_account() {
  echo -e "\n\e[32m### Create account ###\e[0m"
  if [[ "$KEYRING_BACKEND" == "test" ]]; then
    $BIN keys add $WALLET --keyring-backend $KEYRING_BACKEND --home $CONFIG_PATH
  else
    expect -c "
      set timeout -1
      exp_internal 0

      spawn $BIN keys add $WALLET --keyring-backend $KEYRING_BACKEND --home $CONFIG_PATH
      expect \"Enter keyring passphrase*:\"
      send \"$WALLET_PASS\n\"
      expect \"Re-enter keyring passphrase*:\"
      send \"$WALLET_PASS\n\"
      expect eof
    "
  fi
}

start_node() {
  echo -e "\n\e[32m### Run Node ###\e[0m\n"

  case ${NODE_TYPE,,} in
    "app")
      state_sync
      $BIN start ${CONFIG_PATH:+--home $CONFIG_PATH} ${LOG_LEVEL:+--log_level $LOG_LEVEL} ${UPGRADE_HEIGHT:+--v2-upgrade-height $UPGRADE_HEIGHT}
      ;;
    "node")
      $BIN light start ${CHAIN_ID:+--p2p.network $CHAIN_ID} ${CONFIG_PATH:+--node.store $CONFIG_PATH} ${LOG_LEVEL:+--log.level $LOG_LEVEL}
      ;;
  esac
}

set_variable() {
  source ~/.bashrc
  if [[ ! $ACC_ADDRESS ]]
  then
    echo 'export ACC_ADDRESS='$(echo $WALLET_PASS | $BIN keys show $WALLET ${KEYRING_BACKEND:+--keyring-backend $KEYRING_BACKEND} -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$(echo $WALLET_PASS | $BIN keys show $WALLET ${KEYRING_BACKEND:+--keyring-backend $KEYRING_BACKEND} --bech val -a) >> $HOME/.bashrc
  fi
}

case ${NODE_TYPE,,} in
  "app")
    if [[ ! -d "$CONFIG_PATH" || ! -d "$CONFIG_PATH/config" || $(ls -la $CONFIG_PATH/config | grep -cie .*key.json) -eq 0 ]]
    then
      init_node
    fi
    ;;
  "node")
    if [[ ! -d "$CONFIG_PATH" || ! -f "$CONFIG_PATH/config.toml" ]]
    then
      init_node
    fi
    ;;
esac

if [[ $NODE_TYPE == "app" && -n $WALLET && $(find $CONFIG_PATH -maxdepth 2 -type f -name $WALLET.info 2>/dev/null | wc -l) -eq 0 ]]
then
  create_account
fi

if [[ $NODE_TYPE == "app" && -n $WALLET ]]
then
  set_variable
fi

start_node
