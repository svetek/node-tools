##### Download base image Debian 11 and Golang 1.19 #####
FROM golang:1.19-bullseye AS builder

ARG IMAGE_TAG
ARG GIT_REPOSITORY

# Set Working Directory is /app
WORKDIR /app

# Node project build
RUN apt update && apt install clang pkg-config libssl-dev build-essential ncdu -y
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY . && make build
RUN find / -type f -name "libwasmvm.*.so" -exec cp "{}" /app/target/dist/ \;


##### Node Image create #####
FROM debian:bullseye-slim

ARG IMAGE_TAG
ARG BUILD_DATE
LABEL image_tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

#Required variables set by default
ENV KEY="okp4_impulse"
ENV CHAINID="okp4-nemeton"
ENV MONIKER="Okp4Impulse"
ENV KEYRING_BACKEND="test"
ENV KEYALGO="eth_secp256k1"
ENV LOGLEVEL="info"
ENV CONFIG_PATH="/root/.okp4d"

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/dist/okp4d /usr/bin/okp4d
COPY --from=builder /app/target/dist/libwasmvm.x86_64.so /lib/x86_64-linux-gnu/libwasmvm.x86_64.so
COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

EXPOSE 1317 9090 9091 26656 26657

ENTRYPOINT [ "/bin/bash", "/run_node.sh" ]
