# Node Image create
FROM debian:bookworm-slim

ARG BIN
ARG BUILD_DATE
ARG IMAGE_TAG
ARG GIT_REPOSITORY

LABEL image-tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -qO - "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/${BIN}_${IMAGE_TAG#v}_linux_amd64.tar.gz" | tar xz -C /usr/bin --wildcards --no-anchored "*$BIN*"
RUN wget -P /usr/lib https://github.com/CosmWasm/wasmvm/releases/download/v1.3.0/libwasmvm.x86_64.so

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
