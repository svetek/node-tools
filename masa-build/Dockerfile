# Builder Image
FROM golang:1.19-bullseye AS builder

ARG IMAGE_TAG
ARG GIT_REPOSITORY

# Set Working Directory is /app
WORKDIR /app

# Node project build
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY . \
    && cd src \
    && make geth bootnode

# Production Image
FROM debian:bullseye-slim AS runtime

ARG IMAGE_TAG
ARG BUILD_DATE
LABEL image-tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

WORKDIR /app

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*
 
COPY --from=builder /app/src/build/bin/geth /usr/local/bin/
COPY --from=builder /app/src/build/bin/bootnode /usr/local/bin/
COPY --from=builder /app/network/testnet/genesis.json /tmp/conf/genesis.json

RUN echo "{\n\t\"version\":\"$IMAGE_TAG\"\n}" > /tmp/conf/version

COPY run_node.sh /

EXPOSE 8545 8546 30303 30303/udp

ENTRYPOINT [ "/bin/bash", "/run_node.sh" ]