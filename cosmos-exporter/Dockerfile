##### Download base image Debian 11 and Golang 1.19 #####
FROM golang:1.19-bullseye AS builder

ARG IMAGE_TAG
ARG GIT_REPOSITORY

# Set Working Directory is /app
WORKDIR /app

# Project build
RUN apt update && apt install clang pkg-config libssl-dev build-essential ncdu -y
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY . && go build -o cosmos-exporter

##### Image create #####
FROM debian:bullseye-slim AS runtime

ARG IMAGE_TAG
ARG BUILD_DATE
LABEL version=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/cosmos-exporter /usr/bin/cosmos-exporter

EXPOSE 9560

ENTRYPOINT [ "cosmos-exporter" ]
