#!/bin/bash

INDEXER="null"
SNAPSHOT_INTERVAL=0
PRUNING_MODE=custom
PRUNING_INTERVAL=10
PRUNING_KEEP_RECENT=100
MINIMUM_GAS_PRICES=0.002uknow
EXTERNAL_ADDRESS=$(wget -qO- eth0.me)
#BOOTSTRAP_PEERS=$(curl -sL https://raw.githubusercontent.com/celestiaorg/networks/master/mamaki/bootstrap-peers.txt | tr -d '\n')
PERSISTENT_PEERS="994c9398e55947b2f1f45f33fbdbffcbcad655db@okp4-testnet.nodejumper.io:29656,7da790c663d678cb064ff4fba04556dcf18bda2c@65.109.70.23:17656,9340b9190b4189654a58adffbc4428815c5542c8@172.104.248.165:26656,7b0bc30a8427bec0164271147a9ed2c78d374939@185.169.252.242:26659,4fbfd761f07e4fcb8c55aed320518b8030f31961@35.195.110.53:26656,5d4b94f0e1c3f689ae9f0196b4ab1812b8312680@94.103.82.139:26656,807378b8ad2657637ffa7c051f1665a5a54567a6@176.120.177.123:26656,d9085f232712269cfb3d40d845e614d20a368274@195.2.75.148:26656,2c4a1db8418583fcf60f9ab89356af4d2de8a792@193.203.15.86:26656,9d60700e979876e967d2fc2f203b4a677404c202@195.2.81.187:26656,1dee57be85b0d6103c27ef5be786b59895e9c42a@65.108.52.191:26656,3b383a769e0958b3bd44b21b4bc140088207e8dd@45.128.188.221:26656,6fb047e647333b3efe9e536d1825f52b571a6cf4@107.155.91.166:29656,b8fddd530b2d8347212615b6a68c447aba0aed64@161.35.37.194:26656,912f0a4c513b1aa9abb1f5653c4f6c9c6988700d@135.181.222.106:36656,b40df432f97a1f0c319d65ee6ea4c9f92f138d45@94.103.91.231:26656,77b2daf309cd668fc4a5e645df9b09629d6988af@178.18.252.183:26656,dd37382a7cd72d141013e4c77610d519208da12c@185.135.137.160:36656,1cbe918d4cd8eac6b25ef484459286e53ce8acbb@65.109.31.7:36656,5f4bb5cbaedd46eee9de84849d8ca44f8f52571b@195.2.93.79:26656,5f55d5638a1e8aee0de2fd0ec75d1f755402650d@178.208.228.249:26656,488538301bb305f60de2e206c4e63bfdbaa4e72a@65.108.155.121:26656,3ec389c5cf777fb308263e6a5a6cd81e3b86f57e@62.113.113.162:26656,e9bb4d4ae79620e266c075ba29994136b95af5af@178.20.47.160:26656,33aa29630d56f067580f19995ad87ef5e330764e@135.181.25.155:26656,9b87a1b330dc29c0e99a57f56b482f549ca4e312@45.159.249.139:26656,d447c0160314b801ced8252829a00a27bfb5242f@193.33.194.153:26656,5fd27e54731d104eeef6533e5fedfcd1594d90a9@185.245.183.91:26656,9f8098b9e6ec296b9b1dc53ada701886e90aa6be@45.61.161.62:36656,7b0c113dab05557ecedc71b487b34ff5bf686cab@142.93.192.140:36656,42cfb800f0b0767980414ee9b355d2e779adcfbc@94.103.91.192:26656,a56a6a13555b8effadafede915d5532f5e9fa838@46.4.121.72:36656,7f086ff89e53d9d2b2933ea677333b18132d069d@65.108.241.107:26656,153b6e153cd969ed242a15dc6a9bdd2352970394@5.9.199.74:26656,91ab656f63c0a19b796dd5143532c145c791382b@195.2.93.148:26656,c609fee7e1eb9a2188209b304b1d5a3c9b0da0e4@204.48.29.213:36656,c383a523cd6559374bbd1f5d81e61bd11cda0f6f@195.201.197.4:36656,18b6c504471ac2e3327c71b9b0bb9b9bd82a1ec0@135.181.95.36:36656,198202a5e4d3e5d00f244b1f07c153234a33a4cc@178.62.197.195:26656,83a5bec69a78e63f18e665b59a6f162363d8a518@65.108.100.53:34656,4d2d9257724834875f9848f096d264248c1bf2e2@159.65.22.188:26656,670aa91f19ce47c640ccaa7b21a653e1212eebd1@45.84.0.251:26656,993d35035350cd43c6fc07183bf98bd1cbb988df@5.252.23.128:26656,32e2c0a39e6946ff875d814a176833e9304fd98c@94.103.82.200:26656,e76cf197504f3390c64e6ac9ba33e1a585230d5a@84.21.171.170:26656,f926324175f1b82e426ca0733a00b7af5f51de7e@62.171.144.51:53656,53f3e3abee5be9aef0de9adc663c94ae62c911df@135.181.158.205:26656,396e3ed6822e652e74a90adfb52fc353b25ff34d@188.72.78.146:26656,4ae5b488f87cf63fe83fa27cab35b910ea3f3032@185.249.227.170:26656,6238fe1b28838ca0b3878dcabd72556b411918e8@185.209.28.231:26656,29608f98a690d87e6efe365d5c5af980bd678097@65.109.85.226:6070,c140a0e42f4a1b01a698852b3a54b254bcec87f1@185.245.182.58:36656,7ce564e53b8a37167bd8662815eb81d44b62b9de@66.94.115.254:36656,465c8793c32acee902307cfe90d09e16dc984bd4@167.235.225.38:26656,6bcce31ccdab0e1afc73b5874a752741b1f01dd8@62.113.118.160:26656,02d428f4933c832e4a24307704b5181bc7cd43f0@137.184.225.125:2456,4d8406189309d6afb008e87f893d35dd10a9a2ec@45.88.223.161:26656,05582a1692ebcce17bbdd1565e03bb290074034f@20.38.37.130:36656,7ca0f76a967666f3f264b96b55f97eb421e2791e@34.170.76.169:26656,8f04856e3491b97f267bd5716f43d8e11fc0ed42@194.233.67.92:36656,eab52f5e01d4a5c6e214a50e9b87760098b2e64d@188.234.160.105:36656,a1d19b4f6fcb4bca8afb42405a90ce33d592ff15@209.145.56.41:36656,4e7167487ede6b2f77acb28de6482b5b5baa2ae7@5.180.180.137:26656,362812bd8dbdd9f338f52785705d348f3cfb50fb@23.251.135.170:26656,25d94a05b59bc381b25976d6e24a6373a5010cd2@109.123.241.76:36656,a9225a5c513bdc4a2421d0ca4b03b84c9e76ebe5@38.242.245.157:26656,dccc1daa71d64f5e11ac45ae005e5966286801f7@65.108.92.168:26656,bfdfc6b23267a1715c64f06a0b24aa44b4d3a5ac@193.33.195.58:26656,c4ef36ad14700ed5d53fbbf2c94189266afea57a@20.203.98.156:36656,ddcd90ae8e862cc7486b9123878ff6d9e1a2c4d6@193.33.194.246:26656,b098056fd46c830891be193bfc37d0c73201df44@149.102.145.194:36656,2d5d8daa1e1ebd065e6e6e7cfef85470253c198a@74.208.139.222:26656,b6d9d2d20e346213abee3e8864cb77b90f8d0225@95.142.45.197:26656,0f2465585fc6c31f49208e9ddb6480c655ccf07d@144.91.100.18:36656,93d81fae685aebdc0fb17b7047dcc7a53a2d918e@20.115.40.141:36656,cc100439c0a3cbc11ccf7ae100faff356256f983@95.217.177.177:26656,c5c8f6d5847bc7cc73685fcd9030d8d76fc6861d@45.89.54.87:26656,8f778c5ba3e593c12debbb4840750e63dfd9b494@161.97.119.89:36656,10e463b4f649eb0c42a58d0048713349b0589464@161.35.172.245:26656,ff268c0eac517febb43ffe83998ddd441b7500dd@121.66.193.131:36656,017955fac3b0dbe9a7385728128a666652579493@103.19.25.157:26656,2d3df95b5e908b934d88e6e22e3ad9fbf85ab0bd@178.20.46.216:26656,860d80fdc7286725fe09ca20f54291706f180654@104.248.113.179:26656,26418a5e3d2389441bb66c47f3bd20587cb59717@164.92.155.25:26656,de024b927aedb7fc8887c123d12d61598ff6d385@81.5.117.14:36656,b91a184b79e316c38248ebeef700ea9370c6ad97@135.181.252.26:26656,88e7fc9274459d88d28a7748c5253cb62fcf7285@45.14.194.24:26656,2c09bce3a38e9a9d0241e53d7010687c3d69cce7@178.128.93.38:36656,486c6b1c85630f60d2382beec540ed8e21caed86@128.199.180.8:36656,2c49a31c4c763225f65c89aea076f198d58aa379@217.79.187.22:26656,4ed87452cbe6352f359beb84f0d09f04f163798c@94.103.83.150:26656,ba1ad28ac74455335b745f38a90f26b08cad3d47@161.35.162.77:26656,b034a6dec84c56aa94ff479a8d5e6c70d9513994@95.142.47.75:26656,f0b2b77ba9e20cf4e453ca40b0a7a66d3d51f5b9@161.97.160.175:36656,1113ce45fd8f4e943dbcc4ded7a0a66f395e2318@135.181.81.99:26656,7739796b1240071209bb53de2e83d40bf176230e@94.103.84.251:26656,a900056a5a573403840cdd1f7e2fac7c6bd42821@144.91.127.111:36656,09b481ac726f6b9ebea93d8e87dbd414ccb133fa@157.245.147.88:36656,663a2f57306cd3819a31079ec79989cfe7a11680@134.122.62.157:26656,aab352ae37336ebcb11ad4b6e80afd753b77d497@121.78.209.27:26656"

init_node() {
    # Set keyring-backend and chain-id configuration
    okp4d config chain-id $CHAINID --home $CONFIG_PATH
    okp4d config keyring-backend $KEYRING --home $CONFIG_PATH

    # if $KEY exists it should be deleted
    okp4d keys add $KEY --keyring-backend $KEYRING --home $CONFIG_PATH

    # Set moniker and chain-id for Evmos (Moniker can be anything, chain-id must be an integer)
    okp4d init $MONIKER --chain-id $CHAINID --home $CONFIG_PATH

    # Set seeds/bpeers/peers
    sed -i -e "s/^external_address *=.*/external_address = \"$EXTERNAL_ADDRESS:26656\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^filter_peers *=.*/filter_peers = \"true\"/" $CONFIG_PATH/config/config.toml
#   sed -i -e "s/^bootstrap_peers *=.*/bootstrap_peers = \"$BOOTSTRAP_PEERS\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^persistent_peers *=.*/persistent_peers = \"$PERSISTENT_PEERS\"/" $CONFIG_PATH/config/config.toml

    # Config pruning and snapshots
    sed -i -e "s/^indexer *=.*/indexer = \"$INDEXER\"/" $CONFIG_PATH/config/config.toml
    sed -i -e "s/^snapshot-interval *=.*/snapshot-interval = $SNAPSHOT_INTERVAL/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning *=.*/pruning = \"$PRUNING_MODE\"/" $CONFIG_PATH/config/app.toml
    sed -i -e "s/^pruning-keep-recent *=.*/pruning-keep-recent = \"$PRUNING_KEEP_RECENT\"/" $CONFIG_PATH/config/app.toml
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
