# Node Image create
FROM debian:bookworm-slim

ARG BIN
ARG GIT_REPOSITORY
ARG IMAGE_TAG

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect unzip \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

### TODO ###
# RUN wget -qO - /usr/bin/$BIN "${GIT_REPOSITORY}/public/raw/main/mantrachain-testnet/${BIN}-linux-amd64.zip" | unzip \
    # && chmod +x /usr/bin/$BIN
######

### For testnet ###
RUN wget -P /usr/lib https://github.com/CosmWasm/wasmvm/releases/download/v1.3.1/libwasmvm.x86_64.so
COPY ./mantrachaind /usr/bin
RUN chmod ug+x /usr/bin/$BIN
######

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
