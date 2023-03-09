#!/bin/bash

INDEXER=null
SNAPSHOT_INTERVAL=0
PRUNING_MODE=custom
PRUNING_INTERVAL=10
PRUNING_KEEP_EVERY=0
PRUNING_KEEP_RECENT=100
MINIMUM_GAS_PRICES=0.025unibi
EXTERNAL_ADDRESS=$(wget -qO- eth0.me)
SEEDS=$(curl -s https://networks.itn.nibiru.fi/$CHAINID/seeds)
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
    wget -O $CONFIG_PATH/config/genesis.json https://networks.itn.nibiru.fi/$CHAINID/genesis

    # Set seeds/bpeers/peers
    sed -i.bak -e "s/^external_address *=.*/external_address = \"$EXTERNAL_ADDRESS:26656\"/" $CONFIG_PATH/config/config.toml
    sed -i.bak -e "s/^filter_peers *=.*/filter_peers = \"true\"/" $CONFIG_PATH/config/config.toml
    sed -i.bak -e "s/^persistent_peers *=.*/persistent_peers = \"$PEERS\"/" $CONFIG_PATH/config/config.toml
    sed -i.bak -e "s/^seeds *=.*/seeds = \"$SEEDS\"/" $CONFIG_PATH/config/config.toml

    # Config pruning and snapshots
    sed -i.bak -e "s/^indexer *=.*/indexer = \"$INDEXER\"/" $CONFIG_PATH/config/config.toml
    sed -i.bak -e "s/^snapshot-interval *=.*/snapshot-interval = $SNAPSHOT_INTERVAL/" $CONFIG_PATH/config/app.toml
    sed -i.bak -e "s/^pruning *=.*/pruning = \"$PRUNING_MODE\"/" $CONFIG_PATH/config/app.toml
    sed -i.bak -e "s/^pruning-interval *=.*/pruning-interval = \"$PRUNING_INTERVAL\"/" $CONFIG_PATH/config/app.toml
    sed -i.bak -e "s/^pruning-keep-every *=.*/pruning-keep-every = \"$PRUNING_KEEP_EVERY\"/" $CONFIG_PATH/config/app.toml
    sed -i.bak -e "s/^pruning-keep-recent *=.*/pruning-keep-recent = \"$PRUNING_KEEP_RECENT\"/" $CONFIG_PATH/config/app.toml

    # Set min price for GAZ in app.toml
    sed -i.bak -e "s/^minimum-gas-prices *=.*/minimum-gas-prices = \"$MINIMUM_GAS_PRICES\"/" $CONFIG_PATH/config/app.toml
    sed -i.bak -e "s/^max_num_inbound_peers *=.*/max_num_inbound_peers = 50/"  $CONFIG_PATH/config/config.toml
    sed -i.bak -e "s/^max_num_outbound_peers *=.*/max_num_outbound_peers = 50/" $CONFIG_PATH/config/config.toml

    sed -i.bak -e "s/^prometheus *=.*/prometheus = true/" $CONFIG_PATH/config/config.toml

    # Run this to ensure everything worked and that the genesis file is setup correctly
    nibid validate-genesis --home $CONFIG_PATH
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
