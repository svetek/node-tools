## What is Lava

Lava is decentralizing access to blockchain data. It is the first truly unstoppable protocol for blockchain API access.

Serving as a two-sided marketplace that incentivizes and coordinates blockchain nodes to provide dapps with blockchain data, Lava is setting the standard for fast, reliable, and secure API at scale.

> **Lava as a Validator**\
Lava blockchain uses Proof-of-stake (PoS) as the consensus mechanism, based on Tendermint. Validators participate in the network by verifying new blocks to earn rewards.

> **Lava as a Provider**\
Providers are the backbone of the Lava network, servicing relay requests by staking on the network and operating RPC nodes on Relay Chains queried by Consumers (e.g., Cosmos, Ethereum, Osmosis, Polygon, etc.). In return, they earn fees in the form of LAVA tokens from the Consumers for servicing these requests.

## Repository Contents

"build.sh" is a script meticulously crafted for the sole purpose of automating the Docker image assembly process. It serves as the cornerstone of your containerization workflow, simplifying the otherwise complex task of constructing Docker images from source code and configurations.

"run_node.sh" is a versatile script crafted specifically to simplify the deployment and operation of validator and provider nodes in lava blockchain. Whether you are participating in a proof-of-stake network as a validator or providing critical infrastructure as a node operator, this script is your trusted assistant.

A Dockerfile is a plaintext configuration file that provides a step-by-step recipe for building Docker images. These images encapsulate everything needed to run a piece of software, including the application code, runtime environment, dependencies, and configuration files.

A docker-compose.yml is a YAML-formatted configuration file that defines how Docker containers should behave in a multi-container environment. It's the command center for orchestrating your application's containers, specifying services, networking, volumes, and other critical aspects of your containerized setup.

**Build step**:
```bash
michael@u20srv1:~/crypto_node-tools/lava-node$ ./build.sh
What node type is required for build?
1) provider
2) validator
Node type selected: 1
Enter image name: lava
Enter release tag: v0.23.5
Do you want to send the image to DockerHub?
1) yes
2) no
Send the image to DockerHub: 2

### The build information ###
Build date:     2023-09-21
Docker context: /home/michael/crypto_node-tools/lava-node
Dockerfile:     /home/michael/crypto_node-tools/lava-node/Dockerfile
Docker Image:   lava:v0.23.5-provider
Node type:      provider
Version:        v0.23.5

[+] Building 564.3s (10/14)
=> [internal] load .dockerignore
=> => transferring context: 2B
=> [internal] load build definition from Dockerfile
=> => transferring dockerfile: 1.03kB
=> [internal] load metadata for docker.io/library/golang:1.20-bullseye
=> [internal] load metadata for docker.io/library/debian:bullseye-slim
...
=> => naming to docker.io/library/lava:v0.23.5-provider

The build is complete!
```

## Install Docker Engine:

* [Ubuntu](https://docs.docker.com/engine/install/ubuntu)
* [Debian](https://docs.docker.com/engine/install/debian)
* [CentOS](https://docs.docker.com/engine/install/centos)


## Run docker container

**Lava Validator**
```ini
docker run --name lava-validator \
           -e ADDRBOOK_URL="" \
           -e CHAIN_ID=<set chain_id> \
           -e CONFIG_PATH='/root/.lava' \
           -e DIFF_HEIGHT=1000 \
           -e GENESIS_URL=<set genesis url> \
           -e KEY=<set key name> \
           -e KEYRING=<set keyring type> \
           -e KEYALGO=eth_secp256k1 \
           -e LOGLEVEL='info' \
           -e MONIKER=<set moniker name> \
           -e PEERS=<list peers> \
           -e RPC=<url lava rpc> \
           -e PROMETHEUS_PORT=<set prometheus port> \
           -e P2P_PORT=<set p2p port> \
           -e SEEDS=<list seeds> \
           -e STATESYNC='true' \
           -e TOKEN=lava \
           -p 26656:26656 \
           -v ~/.lava/:/root/.lava \
           -d <image:tag>
```
> To create and launch a docker container, you need to define environment variables: CHAINID, KEY, LAVA_RPC, MONIKER, PEERS, SEEDS and specify an lava validator image.

**Lava RPC Provider**
```ini
docker run --name lava-provider \
           -e CHAIN_ID=<set chain_id> \
           -e CONFIG_PATH='/root/.lava' \
           -e GEOLOCATION=<set geolocation> \
           -e KEY=<set key name> \
           -e KEYRING='test' \
           -e KEYALGO=eth_secp256k1 \
           -e LOGLEVEL='info' \
           -e MONIKER=<pool name> \
           -e PROMETHEUS_PORT=<prometheus port> \
           -e REWARDS_STORAGE_DIR=<set rewards dir> \
           -e RPC=<url lava rpc> \
           -e TOTAL_CONNECTIONS=<total connection> \
           -p 26656:26656 \
           -v ~/.lava/:/root/.lava \
           -d <image:tag>
```
> To create and launch a docker container, you need to define environment variables: CHAINID, GEOLOCATION, KEY, LAVA_RPC, MONIKER, PROMETHEUS_PORT, TOTAL_CONNECTIONS and specify an lava provider image.

## Docker container logs
```
docker container logs [OPTIONS] CONTAINER
```
Options:\
--details (Show extra details provided to logs)\
--follow or -f (Follow log output)\
--tail or -n (Number of lines to show from the end of the logs)

ex.: **docker container logs -f lava-provider**


## Run docker compose

```
docker compose up -d
```

## Official Chain IDs

Every chain must have a unique identifier or chain-id. Tendermint requires each application to define its own chain-id in the genesis.json fields.

>lava-testnet-2

| Version name | Block height |
|:------------:|:------------:|
|   v0.21.1.2  |    340778    |
|   v0.22.0    |    396595    |
|   v0.23.5    |    435889    |


## Geolocation
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
*   Image Registry: [DockerHub](https://hub.docker.com/r/svetekllc/lava)
*   Documentation portal: [docs.lavanet.xyz](https://docs.lavanet.xyz/)
