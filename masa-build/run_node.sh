#!/bin/bash

BASEDIR="/app"
CONFIGDIR="/tmp/conf"
GENESIS_FILE="$BASEDIR/genesis.json"
NODE_ID=${NODE_NAME:="Masa$(uname)"}
BOOTNODES="enode:/d004b779ae3728bf83f8e22453404cc3cef16a3d9b96608bc67c4b30db88e0a5a6c6390213f7acbe1153ff6d23ce57380104288ae19373ef@54.146.254.245:21000"

if [[ ! -f $GENESIS_FILE ]]
then
    NETWORK_ID=$(cat ${CONFIGDIR}/genesis.json | grep chainId | awk -F " " '{print $2}' | awk -F "," '{print $1}')
else
    NETWORK_ID=$(cat ${GENESIS_FILE} | grep chainId | awk -F " " '{print $2}' | awk -F "," '{print $1}')
fi

init_node() {
    mkdir -p $BASEDIR/{keystore,geth}
    cp -r $CONFIGDIR/* $BASEDIR 
    geth --datadir $BASEDIR init $GENESIS_FILE
    echo "Created $(date)" > $BASEDIR/control_file
    rm -rf $CONFIGDIR
}

start_node() {
    geth \
    --identity $NODE_ID \
    --datadir $BASEDIR \
    --bootnodes $BOOTNODES \
    --networkid $NETWORK_ID \
    --emitcheckpoints \
    --istanbul.blockperiod 10 \
    --mine \
    --miner.threads 1 \
    --syncmode full
    --verbosity 5 \
    --http \
    --http.corsdomain "*" \
    --http.vhosts "*" \
    --http.addr 0.0.0.0 \
    --http.port 8545 \
    --http.api admin,eth,debug,miner,net,shh,txpool,personal,web3,quorum,istanbul \
    --port 21000
}

if [[ $LOGGING="true" ]]
then
    set -x
fi

if [ ! -f "$BASEDIR/control_file" ]; then
    echo "Node initialization"
    init_node
fi

if [[ -d $CONFIGDIR && $(ls $CONFIGDIR | wc -l) -gt 0 ]]
then
    cp -r $CONFIGDIR/* $BASEDIR 
    rm -rf $CONFIGDIR
fi

echo "Node launch"
start_node