## What is Lava

Lava is decentralizing access to blockchain data. It is the first truly unstoppable protocol for blockchain API access.

Serving as a two-sided marketplace that incentivizes and coordinates blockchain nodes to provide dapps with blockchain data, Lava is setting the standard for fast, reliable, and secure API at scale.

>**Lava as a Validator**\
Lava blockchain uses Proof-of-stake (PoS) as the consensus mechanism, based on Tendermint. Validators participate in the network by verifying new blocks to earn rewards.

>**Lava as a Provider**\
Providers are the backbone of the Lava network, servicing relay requests by staking on the network and operating RPC nodes on Relay Chains queried by Consumers (e.g., Cosmos, Ethereum, Osmosis, Polygon, etc.). In return, they earn fees in the form of LAVA tokens from the Consumers for servicing these requests.


## Install Docker Engine:

* [Ubuntu](https://docs.docker.com/engine/install/ubuntu)
* [Debian](https://docs.docker.com/engine/install/debian)
* [CentOS](https://docs.docker.com/engine/install/centos)


## Run docker container

**Lava Validator**
```ini
docker run --name lava-validator \
           -e CHAINID=<chain id> \
           -e CONFIG_PATH='/root/.lava' \
           -e DIFF_HEIGHT=1000 \
           -e KEY=<key name> \
           -e KEYRING='test' \
           -e KEYALGO=eth_secp256k1 \
           -e LAVA_RPC=<url lava rpc> \
           -e LOGLEVEL='info' \
           -e MONIKER=<pool name> \
           -e PEERS=<list peers> \
           -e SEEDS=<list seeds> \
           -e STATESYNC='true' \
           -p 26656:26656 \
           -v ~/.lava/:/root/.lava \
           -d <image>
```
>To create and launch a docker container, you need to define environment variables: CHAINID, KEY, LAVA_RPC, MONIKER, PEERS, SEEDS and specify an lava validator image.

>The actual values of the variables are given in the current document

**Lava RPC Provider**
```ini
docker run --name lava-provider \
           -e CHAINID=<set chain_id> \
           -e CONFIG_PATH='/root/.lava' \
           -e GEOLOCATION=<set geolocation> \
           -e KEY=<set key name> \
           -e KEYRING='test' \
           -e KEYALGO=eth_secp256k1 \
           -e LAVA_RPC='https://public-rpc-testnet2.lavanet.xyz:443/rpc/' \
           -e LOGLEVEL='info' \
           -e MONIKER=<pool name> \
           -e PROMETHEUS_PORT=<prometheus port> \
           -e TOTAL_CONNECTIONS=<total connection> \
           -p 26656:26656 \
           -v ~/.lava/:/root/.lava \
           -d <image>
```

## Run docker compose

```
docker compose up -d
```

## Official Chain IDs

Every chain must have a unique identifier or chain-id. Tendermint requires each application to define its own chain-id in the genesis.json fields.

> lava-testnet-2

| Version name | Block height |
|:------------:|:------------:|
|   v0.21.1.2  |    340778    |
|   v0.22.0    |    396595    |
|   v0.23.5    |    435889    |


## Geolocation
=
The location of the provider's nodes. (Note that 0 is only assigned via policy/gov proposal)

| Version name |    Block height          |
|:-------------|:-------------------------|
|  GLS = 0     |  Global-strict           |
|  USC = 1     |  US-Center               |
|  EU = 2      |  Europe                  |
|  USE = 4     |  US-East                 |
|  USW = 8     |  US-West                 |
|  AF = 16     |  Africa                  |
|  AS = 32     |  Asia                    |
|  AU = 64     |  Australia, includes NZ  |
|  GL = 65535  |  Global                  |

## Manual configuration node
You can find any details about it by using our documentation [docs.lavanet.xyz](https://docs.lavanet.xyz/testnet/)

## Quick Reference

*   Maintained by: [Lava Network](https://github.com/svetek)
*   Documentation portal: [docs.lavanet.xyz](https://docs.lavanet.xyz/)