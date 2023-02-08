#!/bin/bash

init_node() {
    # Set moniker and chain-id for Haqq (Moniker can be anything, chain-id must be an integer)
    haqqd init $MONIKER --chain-id $CHAINID --home $CONFIG_PATH

    # Set keyring-backend and chain-id configuration
    haqqd config chain-id $CHAINID --home $CONFIG_PATH
    haqqd config keyring-backend $KEYRING --home $CONFIG_PATH

    # if $KEY exists it should be deleted
    haqqd keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH

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
    
    # if you need disable produce empty block, uncomment code below
    # if [[ "$OSTYPE" == "darwin"* ]]; then
    #     sed -i '' 's/create_empty_blocks = true/create_empty_blocks = false/g' $CONFIG_PATH/config/config.toml
    #   else
    #     sed -i 's/create_empty_blocks = true/create_empty_blocks = false/g' $CONFIG_PATH/config/config.toml
    # fi

    if [[ $1 == "pending" ]]; then
      if [[ "$OSTYPE" == "darwin"* ]]; then
          sed -i '' 's/create_empty_blocks_interval = "0s"/create_empty_blocks_interval = "30s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_propose = "3s"/timeout_propose = "30s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_propose_delta = "500ms"/timeout_propose_delta = "5s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_prevote = "1s"/timeout_prevote = "10s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_prevote_delta = "500ms"/timeout_prevote_delta = "5s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_precommit = "1s"/timeout_precommit = "10s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_precommit_delta = "500ms"/timeout_precommit_delta = "5s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_commit = "5s"/timeout_commit = "150s"/g' $CONFIG_PATH/config/config.toml
          sed -i '' 's/timeout_broadcast_tx_commit = "10s"/timeout_broadcast_tx_commit = "150s"/g' $CONFIG_PATH/config/config.toml
      else
          sed -i 's/create_empty_blocks_interval = "0s"/create_empty_blocks_interval = "30s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_propose = "3s"/timeout_propose = "30s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_propose_delta = "500ms"/timeout_propose_delta = "5s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_prevote = "1s"/timeout_prevote = "10s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_prevote_delta = "500ms"/timeout_prevote_delta = "5s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_precommit = "1s"/timeout_precommit = "10s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_precommit_delta = "500ms"/timeout_precommit_delta = "5s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_commit = "5s"/timeout_commit = "150s"/g' $CONFIG_PATH/config/config.toml
          sed -i 's/timeout_broadcast_tx_commit = "10s"/timeout_broadcast_tx_commit = "150s"/g' $CONFIG_PATH/config/config.toml
      fi
    fi

    # Allocate genesis accounts (cosmos formatted addresses)
    # haqqd add-genesis-account $KEY 100000000000000000000000000aISLM --keyring-backend $KEYRING --home $CONFIG_PATH &> /dev/null
    haqqd add-genesis-account $KEY 10000000000000000000aISLM --keyring-backend $KEYRING --home $CONFIG_PATH &> /dev/null

    # Sign genesis transaction
    # haqqd gentx $KEY 1000000000000000000000aISLM --keyring-backend $KEYRING --chain-id $CHAINID --home $CONFIG_PATH &> /dev/null
    haqqd gentx $KEY 10000000000000000000aISLM --chain-id=$CHAINID --moniker=$MONIKER --commission-max-change-rate 0.05 --commission-max-rate 0.20 --commission-rate 0.05 --website="https://adaimpulse.club" --security-contact="" --identity="" --details="Haqq Impulse are the High Availability Stake Pool Cluster with multiple built in redundancies for best possible performance."

    # Collect genesis tx
    haqqd collect-gentxs --home $CONFIG_PATH &> /dev/null

    # Run this to ensure everything worked and that the genesis file is setup correctly
    haqqd validate-genesis --home $CONFIG_PATH

    if [[ $1 == "pending" ]]; then
      echo "pending mode is on, please wait for the first block committed."
    fi

    echo -e "\n### Priv key for Metamask ####"
    haqqd keys unsafe-export-eth-key $KEY --home=$CONFIG_PATH --keyring-backend $KEYRING
    echo -e "\n"
}

start_node() {
  haqqd start --home $CONFIG_PATH --pruning=nothing $TRACE --log_level $LOGLEVEL \
  --minimum-gas-prices=0.0001aISLM \
  --json-rpc.api eth,txpool,personal,net,debug,web3 \
  --json-rpc.enable true --keyring-backend $KEYRING
}

set_variable() {
  if [[ ! $ACC_ADDRESS ]]
  then
    echo 'export ACC_ADDRESS='$(haqqd keys show $KEY -a) >> $HOME/.bashrc
  fi
  if [[ ! $VAL_ADDRESS ]]
  then
    echo 'export VAL_ADDRESS='$(haqqd keys show $KEY --bech val -a) >> $HOME/.bashrc
  fi
}

if [[ $LOGLEVEL && $LOGLEVEL == "debug" ]]
then
  set -x
fi

if [[ ! -d "$CONFIG_PATH" ]] || [[ ! -d "$CONFIG_PATH/config" || $(ls -la $CONFIG_PATH/config | grep -cie .*key.json) -eq 0 ]]
then
  echo "### Initialization node ###"
  init_node
fi

echo "### Run node ###"
set_variable
start_node