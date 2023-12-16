# Builder Image
FROM golang:1.21-bookworm AS builder

ARG BIN=masa-node
ARG GIT_REPOSITORY=https://github.com/masa-finance/masa-oracle-go-testnet
ARG IMAGE_TAG=main

WORKDIR /app

RUN apt-get update && apt-get upgrade -y
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY .
RUN go mod tidy && go build -v -o ${BIN} ./cmd/${BIN}

# Production Image
FROM debian:bookworm-slim

ARG BIN=masa-node
ARG IMAGE_TAG=main
ARG NODE_TYPE=node

LABEL image-tag=$IMAGE_TAG
LABEL node-type=$NODE_TYPE

ENV BIN=$BIN
ENV NODE_TYPE=$NODE_TYPE

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/${BIN} /usr/bin/${BIN}

ENTRYPOINT [ "${BIN}" ]