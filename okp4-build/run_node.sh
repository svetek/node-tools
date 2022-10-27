#!/bin/bash

#TIMEOUT_COMMIT=25s
#PEER_GOSSIP_SLEEP_DURATION=2ms
#MAX_CONNECTIONS=50
#MAX_NUM_INBOUND_PEERS=40
#MAX_NUM_OUTBOUND_PEERS=10
INDEXER="null"
SNAPSHOT_INTERVAL=0
PRUNING_MODE=custom
PRUNING_INTERVAL=10
PRUNING_KEEP_EVERY=0
PRUNING_KEEP_RECENT=100
MINIMUM_GAS_PRICES=0.002uknow
EXTERNAL_ADDRESS=$(wget -qO- eth0.me)
#BOOTSTRAP_PEERS=$(curl -sL https://raw.githubusercontent.com/celestiaorg/networks/master/mamaki/bootstrap-peers.txt | tr -d '\n')
PERSISTENT_PEERS="085cf43f463fe477e6198da0108b0ab08c70c8ab@65.108.75.237:6040,edbc5574b34f34a17273b1af2d1e47aec341ce10@65.108.86.7:26656,2e877dac234099023a9237eb2e5a05cfb3893633@144.76.45.59:16656,ce06cbd4c262108659e10ef9dd79ec489fd0cf65@65.108.57.170:26656,efc552f1211516d578543fc56afcbfbb77c656bd@5.161.145.101:36656,6894c679d851420522baf151e1d1bbf63d9defc9@144.76.97.251:12656,ad5d29c1fc2e5224a51547a677968d84bde76eb8@95.217.118.96:26858,68ed515a400c241543699923f90d3271be8f4d35@65.21.240.218:26656,41a7e27b8e9b0fdda60c786258bfd7b2a3ad1548@65.108.76.44:11684,b827571a11d094886c3742b6ee1dd8453adffbea@173.249.14.133:16656,37444069358f5d1f20c973d037f4819a8e20935a@65.108.13.185:27363,3e96e7f36f3fa2c43735d83ac672fe8db0b63cc8@141.95.65.26:23856"

init_node() {
    # Set keyring-backend and chain-id configuration
    okp4d config chain-id $CHAINID --home $CONFIG_PATH
    okp4d config keyring-backend $KEYRING --home $CONFIG_PATH

    # if $KEY exists it should be deleted
    okp4d keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH

    # Set moniker and chain-id for Evmos (Moniker can be anything, chain-id must be an integer)
    okp4d init $MONIKER --chain-id $CHAINID --home $CONFIG_PATH

    # Set seeds/bpeers/peers
    sed -i -e "s/^external-address *=.*/external-address = \"$EXTERNAL_ADDRESS:26656\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^filter_peers *=.*/filter_peers = \"true\"/" $CONFIG_PATH/config/config.toml
#   sed -i -e "s/^bootstrap-peers *=.*/bootstrap-peers = \"$BOOTSTRAP_PEERS\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^persistent-peers *=.*/persistent-peers = \"$PERSISTENT_PEERS\"/" $CONFIG_PATH/config/config.toml
    
    # Set Consensus Configuration Options
#    sed -i -e "s/^timeout-commit *=.*/timeout-commit = \"$TIMEOUT_COMMIT\"/" $CONFIG_PATH/config/config.toml
#    sed -i -e "s/^peer-gossip-sleep-duration *=.*/peer-gossip-sleep-duration = \"$PEER_GOSSIP_SLEEP_DURATION\"/" $CONFIG_PATH/config/config.toml
    
    # Set P2P Configuration Options
#    sed -i -e "s/^use-legacy *=.*/use-legacy = false/" $CONFIG_PATH/config/config.toml
#    sed -i -e "s/^max-connections *=.*/max-connections = $MAX_CONNECTIONS/" $CONFIG_PATH/config/config.toml
#    sed -i -e "s/^max-num-inbound-peers *=.*/max-num-inbound-peers = $MAX_NUM_INBOUND_PEERS/" $CONFIG_PATH/config/config.toml
#    sed -i -e "s/^max-num-outbound-peers *=.*/max-num-outbound-peers = $MAX_NUM_OUTBOUND_PEERS/" $CONFIG_PATH/config/config.toml

    # Config pruning and snapshots
    sed -i -e "s/^indexer *=.*/indexer = \"$INDEXER\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^snapshot-interval *=.*/snapshot-interval = $SNAPSHOT_INTERVAL/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning *=.*/pruning = \"$PRUNING_MODE\"/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning-keep-recent *=.*/pruning-keep-recent = \"$PRUNING_KEEP_RECENT\"/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning-keep-every *=.*/pruning-keep-every = \"$PRUNING_KEEP_EVERY\"/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning-interval *=.*/pruning-interval = \"$PRUNING_INTERVAL\"/" $CONFIG_PATH/config/app.toml

    # настраиваем минимальную цену за газ в app.toml
    sed -i -e "s/^minimum-gas-prices *=.*/minimum-gas-prices = \"$MINIMUM_GAS_PRICES\"/" $CONFIG_PATH/config/app.toml

    # Sign genesis transaction
    okp4d gentx $KEY 1200000uknow --keyring-backend $KEYRING --chain-id $CHAINID --home $CONFIG_PATH &> /dev/null

    # Download genesis file
    wget -O $CONFIG_PATH/config/genesis.json https://raw.githubusercontent.com/okp4/networks/main/chains/nemeton/genesis.json

    #Allocate genesis accounts (cosmos formatted addresses)
    okp4d add-genesis-account $KEY 1200000uknow --keyring-backend $KEYRING --home $CONFIG_PATH &> /dev/null

    # Run this to ensure everything worked and that the genesis file is setup correctly
    okp4d validate-genesis --home $CONFIG_PATH
}

start_node() {
  okp4d start --home $CONFIG_PATH --pruning=nothing --log_level $LOGLEVEL
}

set_variable() {
  if [[ ! $ACC_ADDRESS ]]
  then  
    echo 'export ACC_ADDRESS='$(okp4d keys show $KEY -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$(okp4d keys show $KEY --bech val -a) >> $HOME/.bashrc
  fi
}

set -x

if [[ $LOGLEVEL && $LOGLEVEL == "debug" ]]
then
  set -x
fi

if [[ -d "$CONFIG_PATH" ]] && [[ -d "$CONFIG_PATH/config" && $(ls -la $CONFIG_PATH/config | grep -cie .*key.json) -gt 0 ]]
then
  echo "### Run node ###"
  set_variable
  start_node
else
  echo "### Initialization node ###"
  init_node
  echo "### Run node ###"
  set_variable
  start_node
fi
