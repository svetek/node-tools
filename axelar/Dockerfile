# Node Image create
FROM debian:bookworm-slim

ARG BIN
ARG GIT_REPOSITORY
ARG IMAGE_TAG

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -P /usr/lib https://github.com/CosmWasm/wasmvm/releases/download/v2.2.4/libwasmvm.x86_64.so
RUN wget -qO /usr/bin/$BIN "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/${BIN}-linux-amd64-${IMAGE_TAG}" \
    && chmod +x /usr/bin/$BIN

ENTRYPOINT [ "axelard" ]
