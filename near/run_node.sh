#!/bin/bash
set -e

if [[ ! -f $CONFIG_PATH/node_key.json ]]
then
    echo -e "\e[32m### Initialization node ###\e[0m\n"
    $BIN ${CONFIG_PATH:+--home="$CONFIG_PATH"} init \
         ${CHAIN_ID:+--chain-id="$CHAIN_ID"} \
         ${ACCOUNT_ID:+--account-id="$ACCOUNT_ID"} \
         ${BOOT_NODES:+--boot-nodes="$BOOT_NODES"} \
         --download-genesis \
         --download-config
fi

echo -e "\n\e[32m### Run Node ###\e[0m\n"
exec $BIN ${CONFIG_PATH:+--home="$CONFIG_PATH"} run \
          ${BOOT_NODES:+--boot-nodes="$BOOT_NODES"}
