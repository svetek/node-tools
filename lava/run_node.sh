#!/bin/bash

init_node() {
  echo -e "\e[32m### Initialization node ###\e[0m\n"

  # Set moniker and chain-id for Lava (Moniker can be anything, chain-id must be an integer)
  $BIN init $MONIKER --chain-id $CHAIN_ID --home $CONFIG_PATH

  # Set keyring-backend and chain-id configuration
  $BIN config chain-id $CHAIN_ID --home $CONFIG_PATH
  $BIN config keyring-backend $KEYRING --home $CONFIG_PATH

  # Download genesis and addrbook files
  wget -O $CONFIG_PATH/config/genesis.json $GENESIS_URL

  if [[ -n $ADDRBOOK_URL ]]
  then
    wget -O $CONFIG_PATH/config/addrbook.json $ADDRBOOK_URL
  fi

  sed -i \
    -e 's|^broadcast-mode *=.*|broadcast-mode = "sync"|' \
    $CONFIG_PATH/config/client.toml

  # Set seeds/peers
  sed -i \
    -e 's|^indexer =.*|indexer = "null"|' \
    -e 's|^filter_peers =.*|filter_peers = "true"|' \
    -e "s|^persistent_peers =.*|persistent_peers = \"$PEERS\"|" \
    -e "s|^seeds =.*|seeds = \"$SEEDS\"|" \
    -e 's|^create_empty_blocks =.*|create_empty_blocks = true|' \
    -e 's|^create_empty_blocks_interval =.*|create_empty_blocks_interval = "60s"|' \
    $CONFIG_PATH/config/config.toml

  # Set timeout
  sed -i \
    -e 's|^timeout_commit =.*|timeout_commit = "30s"|' \
    -e 's|^timeout_propose =.*|timeout_propose = "1s"|' \
    -e 's|^timeout_precommit =.*|timeout_precommit = "1s"|' \
    -e 's|^timeout_precommit_delta =.*|timeout_precommit_delta = "500ms"|' \
    -e 's|^timeout_prevote =.*|timeout_prevote = "1s"|' \
    -e 's|^timeout_prevote_delta =.*|timeout_prevote_delta = "500ms"|' \
    -e 's|^timeout_propose_delta =.*|timeout_propose_delta = "500ms"|' \
    -e 's|^skip_timeout_commit =.*|skip_timeout_commit = false|' \
    $CONFIG_PATH/config/config.toml

  # Set ports P2P and Prometheus
  sed -i \
    -e "s|^prometheus =.*|prometheus = true|" \
    -e "s|^prometheus_listen_addr =.*|prometheus_listen_addr = \":$METRICS_PORT\"|" \
    -e "s|laddr = \"tcp://0.0.0.0:26656\"|laddr = \"tcp://0.0.0.0:$P2P_PORT\"|" \
    -e "s|^external_address *=.*|external_address = \"$(wget -qO- eth0.me):$P2P_PORT\"|" \
    $CONFIG_PATH/config/config.toml

  # Config pruning, snapshots and min price for GAZ
  sed -i \
    -e 's|^snapshot-interval =.*|snapshot-interval = 0|' \
    -e 's|^pruning =.*|pruning = "custom"|' \
    -e 's|^pruning-keep-recent =.*|pruning-keep-recent = "100"|' \
    -e 's|^pruning-interval =.*|pruning-interval = "10"|' \
    -e "s|^minimum-gas-prices =.*|minimum-gas-prices = \"0.0025u${TOKEN}\"|" \
    $CONFIG_PATH/config/app.toml
}

state_sync() {
  if [[ $STATE_SYNC && $STATE_SYNC == "true" ]]
  then
    LATEST_HEIGHT=$(curl -s $RPC/block | jq -r .result.block.header.height)
    SYNC_BLOCK_HEIGHT=$(($LATEST_HEIGHT - $DIFF_HEIGHT))
    SYNC_BLOCK_HASH=$(curl -s "$RPC/block?height=$SYNC_BLOCK_HEIGHT" | jq -r .result.block_id.hash)
    sed -i \
      -e 's|^enable =.*|enable = true|' \
      -e "s|^rpc_servers =.*|rpc_servers = \"$RPC,$RPC\"|" \
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
  $BIN keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH
}

create_endpoins_conf() {
  cat > "$CONFIG_PATH/config/rpcprovider.yml" <<_EOF_
endpoints:
  - api-interface: tendermintrpc
    chain-id: LAV1
    network-address:
      address: 0.0.0.0:22001
      disable-tls: true
    node-urls:
      - url: https://public-rpc-testnet2.lavanet.xyz:443/rpc/
_EOF_
}

start_node() {
  case ${NODE_TYPE,,} in
    "cache")
      echo -e "\n\e[32m### Run Cache ###\e[0m\n"
      args=(
            "$CACHE_LISTEN_ADDRESS:$CACHE_PORT" \
            "--metrics_address $METRICS_LISTEN_ADDRESS:$METRICS_PORT" \
            "--log_level $LOGLEVEL"
      )
      $BIN cache ${args[@]}
      ;;

    "provider")
      echo -e "\n\e[32m### Run RPC Provider ###\e[0m\n"
      [[ ! -f "$CONFIG_PATH/config/rpcprovider.yml" ]] && create_endpoins_conf
      args=(
            "--chain-id $CHAIN_ID" \
            "--from $KEY" \
            "--geolocation $GEOLOCATION" \
            "--home $CONFIG_PATH" \
            "--keyring-backend $KEYRING" \
            "--log_level $LOGLEVEL" \
            "--metrics-listen-address $METRICS_LISTEN_ADDRESS:$METRICS_PORT" \
            "--node $RPC" \
            "--parallel-connections $TOTAL_CONNECTIONS" \
            "--reward-server-storage $CONFIG_PATH/$REWARDS_STORAGE_DIR" \
      )
      [[ $CACHE_ENABLE == "true" ]] && args+=( "--cache-be $CACHE_ADDRESS:$CACHE_PORT" )
      $BIN rpcprovider ${args[@]}
      ;;

    "validator")
      echo -e "\n\e[32m### Run Validator Node ###\e[0m\n"
      state_sync
      $BIN start --home $CONFIG_PATH --log_level $LOGLEVEL
      ;;
  esac
}

set_variable() {
  source ~/.bashrc
  if [[ ! $ACC_ADDRESS ]]
  then
    echo 'export ACC_ADDRESS='$($BIN keys show $KEY --keyring-backend $KEYRING -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$($BIN keys show $KEY --keyring-backend $KEYRING --bech val -a) >> $HOME/.bashrc
  fi
}

if [[ $LOGLEVEL && $LOGLEVEL == "debug" ]]
then
  set -x
fi

if [[ $NODE_TYPE == "validator" ]] && [[ ! -d "$CONFIG_PATH/config" || $(ls -la $CONFIG_PATH/config | grep -cie .*key.json) -eq 0 ]]
then
  init_node
fi

if [[ $NODE_TYPE == "validator" || $NODE_TYPE == "provider" ]] && [[ $(find $CONFIG_PATH -maxdepth 2 -type f -name $KEY.info | wc -l) -eq 0 ]]
then
  create_account
fi

if [[ $NODE_TYPE == "validator" || $NODE_TYPE == "provider" ]]
then
  set_variable
fi

start_node
