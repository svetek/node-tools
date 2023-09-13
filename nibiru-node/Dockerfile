#Download base image Debian 11 and Golang 1.19
FROM golang:1.19-bullseye AS builder

ARG IMAGE_TAG
ARG GIT_REPOSITORY

# Set Working Directory is /app
WORKDIR /app

# Node project build
RUN apt update && apt install clang pkg-config libssl-dev build-essential ncdu -y
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY . && make build
RUN find / -type f -name "libwasmvm.x86_64.so" -exec cp "{}" /app/build/ \;

# Node Image create
FROM debian:bullseye-slim

ARG IMAGE_TAG
ARG BUILD_DATE
LABEL image-tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

# Required variables set by default
# KEY_PASS env must be at least 8 characters
ENV KEY="<key name>"
ENV KEY_PASS="<insert password>"
ENV CHAINID="nibiru-itn-1"
ENV MONIKER="<moniker name>"
ENV KEYRING="file"
ENV KEYALGO="eth_secp256k1"
ENV LOGLEVEL="info"
ENV CONFIG_PATH="/root/.nibid"

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/build/nibid /usr/bin/nibid
COPY --from=builder /app/build/libwasmvm.x86_64.so /lib/x86_64-linux-gnu/libwasmvm.x86_64.so
COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "/bin/bash", "/run_node.sh" ]
