#!/bin/bash

init_node() {
  echo -e "\n\e[32m### Initialization node ###\e[0m\n"

  # Set moniker and chain-id for Lava (Moniker can be anything, chain-id must be an integer)
  $LAVA_BINARY init $MONIKER --chain-id $CHAINID --home $CONFIG_PATH

  # Set keyring-backend and chain-id configuration
  $LAVA_BINARY config chain-id $CHAINID --home $CONFIG_PATH
  $LAVA_BINARY config keyring-backend $KEYRING --home $CONFIG_PATH

  # Download genesis file
  wget -O $CONFIG_PATH/config/genesis.json https://raw.githubusercontent.com/lavanet/lava-config/main/testnet-2/genesis_json/genesis.json

  sed -i \
    -e 's|^broadcast-mode *=.*|broadcast-mode = "sync"|' \
    $CONFIG_PATH/config/client.toml

  # Set seeds/peers
  sed -i \
    -e 's|^indexer *=.*|indexer = "null"|' \
    -e "s|^external_address *=.*|external_address = \"$(wget -qO- eth0.me):26656\"|" \
    -e 's|^filter_peers *=.*|filter_peers = "true"|' \
    -e "s|^persistent_peers *=.*|persistent_peers = \"$PEERS\"|" \
    -e "s|^seeds *=.*|seeds = \"$SEEDS\"|" \
    -e 's|^create_empty_blocks *=.*|create_empty_blocks = true|' \
    -e 's|^create_empty_blocks_interval *=.*|create_empty_blocks_interval = "60s"|' \
    $CONFIG_PATH/config/config.toml

  # Set timeout
  sed -i \
    -e 's|^timeout_commit *=.*|timeout_commit = "30s"|' \
    -e 's|^timeout_propose *=.*|timeout_propose = "1s"|' \
    -e 's|^timeout_precommit *=.*|timeout_precommit = "1s"|' \
    -e 's|^timeout_precommit_delta *=.*|timeout_precommit_delta = "500ms"|' \
    -e 's|^timeout_prevote *=.*|timeout_prevote = "1s"|' \
    -e 's|^timeout_prevote_delta *=.*|timeout_prevote_delta = "500ms"|' \
    -e 's|^timeout_propose_delta *=.*|timeout_propose_delta = "500ms"|' \
    -e 's|^skip_timeout_commit *=.*|skip_timeout_commit = false|' \
    $CONFIG_PATH/config/config.toml

  # Config pruning, snapshots and min price for GAZ
  sed -i \
    -e 's|^snapshot-interval *=.*|snapshot-interval = 0|' \
    -e 's|^pruning *=.*|pruning = "custom"|' \
    -e 's|^pruning-keep-recent *=.*|pruning-keep-recent = "100"|' \
    -e 's|^pruning-interval *=.*|pruning-interval = "10"|' \
    -e 's|^minimum-gas-prices *=.*|minimum-gas-prices = "0.0025ulava"|' \
    $CONFIG_PATH/config/app.toml

  LATEST_HEIGHT=$(curl -s $LAVA_RPC/block | jq -r .result.block.header.height)
  if [[ $LATEST_HEIGHT -gt $DIFF_HEIGHT ]]
  then 
    SYNC_BLOCK_HEIGHT=$(($LATEST_HEIGHT - $DIFF_HEIGHT))
    SYNC_BLOCK_HASH=$(curl -s "$LAVA_RPC/block?height=$SYNC_BLOCK_HEIGHT" | jq -r .result.block_id.hash)
    sed -i \
      -e 's|^enable *=.*|enable = true|' \
      -e "s|^rpc_servers *=.*|rpc_servers = \"$LAVA_RPC\"|" \
      -e "s|^trust_height *=.*|trust_height = $SYNC_BLOCK_HEIGHT|" \
      -e "s|^trust_hash *=.*|trust_hash = \"$SYNC_BLOCK_HASH\"|" \
      $CONFIG_PATH/config/config.toml
  fi
}

create_account() {
  echo -e "\n\e[32m### Create account ###\e[0m"
  $LAVA_BINARY keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH
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

    "validator node")
      echo -e "\n\e[32m### Run Validator Node ###\e[0m\n"
      $LAVA_BINARY start --home $CONFIG_PATH \
                         --pruning=nothing \
                         --log_level $LOGLEVEL
      ;;

    "rpc node")
      echo -e "\n\e[32m### Run RPC Node ###\e[0m\n"
      [[ ! -f "$CONFIG_PATH/config/rpcprovider.yml" ]] && create_endpoins_conf
      $LAVA_BINARY rpcprovider --home $CONFIG_PATH \
                               --from $KEY \
                               --keyring-backend $KEYRING \
                               --geolocation $GEOLOCATION \
                               --chain-id $CHAINID \
                               --parallel-connections $TOTAL_CONNECTIONS \
                               --metrics-listen-address ":$PROMETHEUS_PORT" \
                               --log_level $LOGLEVEL \
                               --node $LAVA_RPC
      ;;
  esac
}

set_variable() {
  source ~/.bashrc
  if [[ ! $ACC_ADDRESS ]]
  then
    echo 'export ACC_ADDRESS='$($LAVA_BINARY keys show $KEY --keyring-backend $KEYRING -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$($LAVA_BINARY keys show $KEY --keyring-backend $KEYRING --bech val -a) >> $HOME/.bashrc
  fi
}

if [[ $LOGLEVEL && $LOGLEVEL == "debug" ]]
then
  set -x
fi

if [[ $NODE_TYPE == "Validator Node" ]] && [[ ! -d "$CONFIG_PATH/config" || $(ls -la $CONFIG_PATH/config | grep -cie .*key.json) -eq 0 ]]
then
  init_node
fi

if [[ $(find $CONFIG_PATH -maxdepth 2 -type f -name $KEY.info | wc -l) -eq 0 ]]
then
  create_account
fi

set_variable
start_node
