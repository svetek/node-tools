# Node Image create
FROM debian:bookworm-slim

ARG BIN
ARG GIT_REPOSITORY
ARG IMAGE_TAG

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect procps \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -P /usr/lib https://github.com/CosmWasm/wasmvm/releases/download/v1.5.4/libwasmvm.x86_64.so
RUN wget -qO - "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/${BIN}-${IMAGE_TAG#v}-linux-amd64.tar.gz" | tar xz -C /usr/bin --wildcards --no-anchored "*$BIN*"

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
