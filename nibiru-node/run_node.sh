#!/bin/bash

SEEDS=$(curl -s https://networks.itn2.nibiru.fi/$CHAINID/seeds)
PEERS=""

init_node() {
    # Set moniker and chain-id for Haqq (Moniker can be anything, chain-id must be an integer)
    nibid init $MONIKER --chain-id $CHAINID --home $CONFIG_PATH

    # Set keyring-backend and chain-id configuration
    nibid config chain-id $CHAINID --home $CONFIG_PATH
    nibid config keyring-backend $KEYRING --home $CONFIG_PATH

    # if $KEY exists it should be deleted
    echo -e "\n\e[32m### Wallet info ###\e[0m"
    (echo $KEY_PASS; echo $KEY_PASS) | nibid keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH

    # Download genesis file
    wget -O $CONFIG_PATH/config/genesis.json https://networks.itn2.nibiru.fi/$CHAINID/genesis

    # Set seeds/peers
    sed -i \
      -e 's|^indexer *=.*|indexer = "null"|' \
      -e 's|^filter_peers *=.*|filter_peers = "true"|' \
      -e "s|^external_address *=.*|external_address = \"$(wget -qO- eth0.me):26656\"|" \
      -e "s|^persistent_peers *=.*|persistent_peers = \"$PEERS\"|" \
      -e "s|^seeds *=.*|seeds = \"$SEEDS\"|" \
      -e 's|^prometheus *=.*|prometheus = true|' \
      -e 's|^max_num_inbound_peers *=.*|max_num_inbound_peers = 50|' \
      -e 's|^max_num_outbound_peers *=.*|max_num_outbound_peers = 50|' \
      $CONFIG_PATH/config/config.toml

    # Config pruning, snapshots and min price for GAZ
    sed -i \
      -e 's|^snapshot-interval *=.*|snapshot-interval = 0|' \
      -e 's|^pruning *=.*|pruning = "custom"|' \
      -e 's|^pruning-interval *=.*|pruning-interval = "10"|' \
      -e 's|^pruning-keep-every *=.*|pruning-keep-every = "0"|' \
      -e 's|^pruning-keep-recent *=.*|pruning-keep-recent = "100"|' \
      -e 's|^minimum-gas-prices *=.*|minimum-gas-prices = "0.025unibi"|' \
      $CONFIG_PATH/config/app.toml
}

start_node() {
  (echo $KEY_PASS) | nibid start --home $CONFIG_PATH --log_level $LOGLEVEL
}

set_variable() {
  if [[ ! $ACC_ADDRESS ]]
  then
    echo 'export ACC_ADDRESS='$(echo $KEY_PASS | nibid keys show $KEY -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$(echo $KEY_PASS | nibid keys show $KEY --bech val -a) >> $HOME/.bashrc
  fi
}

if [[ $LOGLEVEL && $LOGLEVEL == "debug" ]]
then
  set -x
fi

if [[ ! -d "$CONFIG_PATH" ]] || [[ ! -d "$CONFIG_PATH/config" || $(ls -la $CONFIG_PATH/config | grep -cie .*key.json) -eq 0 ]]
then
  echo -e "\n\e[32m### Initialization node ###\e[0m\n"
  init_node
fi

echo -e "\n\e[32m### Run node ###\e[0m\n"
set_variable
start_node
