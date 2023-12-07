#!/bin/bash

MODE=validator
TIMEOUT_COMMIT=25s
PEER_GOSSIP_SLEEP_DURATION=2ms
MAX_CONNECTIONS=50
MAX_NUM_INBOUND_PEERS=40
MAX_NUM_OUTBOUND_PEERS=10
SNAPSHOT_INTERVAL=0
PRUNING_MODE=custom
PRUNING_INTERVAL=10
PRUNING_KEEP_RECENT=100
MINIMUM_GAS_PRICES=0.0025utia
EXTERNAL_ADDRESS=$(wget -qO- eth0.me)
BOOTSTRAP_PEERS=$(curl -sL https://raw.githubusercontent.com/celestiaorg/networks/master/mamaki/bootstrap-peers.txt | tr -d '\n')
PERSISTENT_PEERS=$(curl -sL https://raw.githubusercontent.com/celestiaorg/networks/master/mamaki/peers.txt | tr -d '\n')

init_node() { 
    # Set keyring-backend and chain-id configuration
    celestia-appd config keyring-backend $KEYRING --home $CONFIG_PATH
    celestia-appd config chain-id $CHAINID --home $CONFIG_PATH

    # if $KEY exists it should be deleted
    celestia-appd keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH

    # Set moniker and chain-id for Evmos (Moniker can be anything, chain-id must be an integer)
    celestia-appd init $MONIKER --chain-id $CHAINID --home $CONFIG_PATH

    # Set Validator mode
    sed -i -e "s/^mode *=.*/mode = \"$MODE\"/" $CONFIG_PATH/config/config.toml    

    # Set seeds/bpeers/peers
    sed -i -e "s/^external-address *=.*/external-address = \"$EXTERNAL_ADDRESS:26656\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^bootstrap-peers *=.*/bootstrap-peers = \"$BOOTSTRAP_PEERS\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^persistent-peers *=.*/persistent-peers = \"$PERSISTENT_PEERS\"/" $CONFIG_PATH/config/config.toml
    
    # Set Consensus Configuration Options
    sed -i -e "s/^timeout-commit *=.*/timeout-commit = \"$TIMEOUT_COMMIT\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^peer-gossip-sleep-duration *=.*/peer-gossip-sleep-duration = \"$PEER_GOSSIP_SLEEP_DURATION\"/" $CONFIG_PATH/config/config.toml
    
    # Set P2P Configuration Options
    sed -i -e "s/^use-legacy *=.*/use-legacy = false/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^max-connections *=.*/max-connections = $MAX_CONNECTIONS/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^max-num-inbound-peers *=.*/max-num-inbound-peers = $MAX_NUM_INBOUND_PEERS/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^max-num-outbound-peers *=.*/max-num-outbound-peers = $MAX_NUM_OUTBOUND_PEERS/" $CONFIG_PATH/config/config.toml

    # Config pruning and snapshots
    sed -i -e "s/^pruning *=.*/pruning = \"$PRUNING_MODE\"/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^snapshot-interval *=.*/snapshot-interval = $SNAPSHOT_INTERVAL/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning-keep-recent *=.*/pruning-keep-recent = \"$PRUNING_KEEP_RECENT\"/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning-interval *=.*/pruning-interval = \"$PRUNING_INTERVAL\"/" $CONFIG_PATH/config/app.toml

    # настраиваем минимальную цену за газ в app.toml
    sed -i -e "s/^minimum-gas-prices *=.*/minimum-gas-prices = \"$MINIMUM_GAS_PRICES\"/" $CONFIG_PATH/config/app.toml

    #Allocate genesis accounts (cosmos formatted addresses)
    celestia-appd add-genesis-account $KEY 10000000000000000000000000utia --keyring-backend $KEYRING --home $CONFIG_PATH &> /dev/null

    # Sign genesis transaction
    celestia-appd gentx $KEY 1000000000utia --keyring-backend $KEYRING --chain-id $CHAINID --home $CONFIG_PATH &> /dev/null

    # Collect genesis tx
    celestia-appd collect-gentxs --home $CONFIG_PATH &> /dev/null

    # Run this to ensure everything worked and that the genesis file is setup correctly
    celestia-appd validate-genesis --home $CONFIG_PATH
}

start_node() { 
  celestia-appd start --home $CONFIG_PATH --chain-id $CHAIN_ID --log_level $LOGLEVEL
}

set_variable() {
  if [[ ! $ACC_ADDRESS ]]
  then  
    echo 'export ACC_ADDRESS='$(celestia-appd keys show $KEY -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$(celestia-appd keys show $KEY --bech val -a) >> $HOME/.bashrc 
  fi
}

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
