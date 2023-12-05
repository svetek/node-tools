#!/bin/bash

BASEDIR="/app"
SOURCE_DIR="/source"
MN_WORKDIR="$BASEDIR/massa-node"
MC_WORKDIR="$BASEDIR/massa-client"

if [[ $LOGGING == "true" ]]
then
    set -x
fi

### Massa node and client install/update ###
if [[ $(ls $SOURCE_DIR | wc -l) -gt 0 ]]
then
    if [[ ! -d $MC_WORKDIR || ! -d $MN_WORKDIR ]]
    then
        mkdir -p $MC_WORKDIR $MN_WORKDIR
        cp -rf $SOURCE_DIR/massa-client/* $MC_WORKDIR
        cp -rf $SOURCE_DIR/massa-node/* $MN_WORKDIR
        cp -f $SOURCE_DIR/version.json $BASEDIR

        echo -e "\e[32m### Massa Node and Massa Client installation complete successfully. ###\e[0m\n"
        echo "1) $(${MN_WORKDIR}/massa-node -V) ver."
        echo "2) $(${MC_WORKDIR}/massa-client -V) ver."
    else
        ver_old=$(cat $BASEDIR/version.json 2>/dev/null | jq -r .version)
        ver=${ver_old:="unknown.bak"}
        cp -f $SOURCE_DIR/massa-client/massa-client $MC_WORKDIR
        cp -f $SOURCE_DIR/massa-node/massa-node $MN_WORKDIR
        cp -fbr -S "-$ver.bak" $SOURCE_DIR/massa-client/{config,base_config} $MC_WORKDIR
        cp -fbr -S "-$ver.bak" $SOURCE_DIR/massa-node/{config,base_config} $MN_WORKDIR
        cp -f $SOURCE_DIR/version.json $BASEDIR

        echo -e "\n\e[32m### Massa Node and Massa Client update complete successfully. ###\e[0m\n"
        echo "1) $(${MN_WORKDIR}/massa-node -V) ver."
        echo "2) $(${MC_WORKDIR}/massa-client -V) ver."
    fi
    echo -e "[network]\nroutable_ip = \"`wget -qO- eth0.me`\"" > $MN_WORKDIR/config/config.toml
    echo 'alias massa-client="cd /app/massa-client && ./massa-client -p $PASSWORD"' >> $HOME/.bashrc
    rm -rf $SOURCE_DIR/*
fi

echo -e "\n\e[32m### Massa Node is running successfully ###\e[0m\n"
cd $MN_WORKDIR && ./$BIN -p $PASSWORD
