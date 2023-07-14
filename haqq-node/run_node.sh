#!/bin/bash

INDEXER="null"
SNAPSHOT_INTERVAL=0
PRUNING_MODE=custom
PRUNING_INTERVAL=10
PRUNING_KEEP_EVERY=0
PRUNING_KEEP_RECENT=100
MINIMUM_GAS_PRICES=0.0025aISLM
EXTERNAL_ADDRESS=$(wget -qO- eth0.me)
SEEDS="62bf004201a90ce00df6f69390378c3d90f6dd7e@seed2.testedge2.haqq.network:26656,23a1176c9911eac442d6d1bf15f92eeabb3981d5@seed1.testedge2.haqq.network:26656"
PEERS=""

init_node() {
    # Set moniker and chain-id for Haqq (Moniker can be anything, chain-id must be an integer)
    haqqd init $MONIKER --chain-id $CHAINID --home $CONFIG_PATH

    # Set keyring-backend and chain-id configuration
    haqqd config chain-id $CHAINID --home $CONFIG_PATH
    haqqd config keyring-backend $KEYRING --home $CONFIG_PATH

    # if $KEY exists it should be deleted
    echo -e "\n\e[32m### Wallet info ###\e[0m"

    expect -c "
        #!/usr/bin/expect -f
        set timeout -1

        spawn haqqd keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH
        exp_internal 0
        expect \"Enter keyring passphrase:\"
        send   \"$KEYPASS\n\"
        expect \"Re-enter keyring passphrase:\"
        send   \"$KEYPASS\n\"
        expect eof
    "

    # Change parameter token denominations to aISLM
    cat $CONFIG_PATH/config/genesis.json | jq '.app_state["staking"]["params"]["bond_denom"]="aISLM"' > $CONFIG_PATH/config/tmp_genesis.json && mv $CONFIG_PATH/config/tmp_genesis.json $CONFIG_PATH/config/genesis.json
    cat $CONFIG_PATH/config/genesis.json | jq '.app_state["crisis"]["constant_fee"]["denom"]="aISLM"' > $CONFIG_PATH/config/tmp_genesis.json && mv $CONFIG_PATH/config/tmp_genesis.json $CONFIG_PATH/config/genesis.json
    cat $CONFIG_PATH/config/genesis.json | jq '.app_state["gov"]["deposit_params"]["min_deposit"][0]["denom"]="aISLM"' > $CONFIG_PATH/config/tmp_genesis.json && mv $CONFIG_PATH/config/tmp_genesis.json $CONFIG_PATH/config/genesis.json
    cat $CONFIG_PATH/config/genesis.json | jq '.app_state["mint"]["params"]["mint_denom"]="aISLM"' > $CONFIG_PATH/config/tmp_genesis.json && mv $CONFIG_PATH/config/tmp_genesis.json $CONFIG_PATH/config/genesis.json
    cat $CONFIG_PATH/config/genesis.json | jq '.app_state["evm"]["params"]["evm_denom"]="aISLM"' > $CONFIG_PATH/config/tmp_genesis.json && mv $CONFIG_PATH/config/tmp_genesis.json $CONFIG_PATH/config/genesis.json

    # 1 min for proposal's vote vaiting
    cat $CONFIG_PATH/config/genesis.json | jq '.app_state["gov"]["voting_params"]["voting_period"]="60s"' > $CONFIG_PATH/config/tmp_genesis.json && mv $CONFIG_PATH/config/tmp_genesis.json $CONFIG_PATH/config/genesis.json

    # Set gas limit in genesis
    cat $CONFIG_PATH/config/genesis.json | jq '.consensus_params["block"]["max_gas"]="10000000"' > $CONFIG_PATH/config/tmp_genesis.json && mv $CONFIG_PATH/config/tmp_genesis.json $CONFIG_PATH/config/genesis.json

    # Allocate genesis accounts (cosmos formatted addresses)
    (echo $KEYPASS) | haqqd add-genesis-account $KEY 10000000000000000000aISLM --keyring-backend $KEYRING --home $CONFIG_PATH &> /dev/null

    # Sign genesis transaction
    (echo $KEYPASS) | haqqd gentx $KEY 10000000000000000000aISLM --chain-id=$CHAINID --moniker=$MONIKER --commission-max-change-rate 0.05 --commission-max-rate 0.20 --commission-rate 0.05 &> /dev/null

    # Collect genesis tx
    (echo $KEYPASS) | haqqd collect-gentxs --home $CONFIG_PATH &> /dev/null

    # Run this to ensure everything worked and that the genesis file is setup correctly
    (echo $KEYPASS) | haqqd validate-genesis --home $CONFIG_PATH

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
    sed -i.bak -e "s/^max_num_outbound_peers *=.*/max_num_outbound_peers = 25/" $CONFIG_PATH/config/config.toml
}

start_node() {
  (echo $KEYPASS) | haqqd start --home $CONFIG_PATH --log_level $LOGLEVEL
}

set_variable() {
  source ~/.bashrc
  if [[ ! $ACC_ADDRESS ]]
  then
    echo 'export ACC_ADDRESS='$(echo $KEYPASS | haqqd keys show $KEY -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$(echo $KEYPASS | haqqd keys show $KEY --bech val -a) >> $HOME/.bashrc
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
