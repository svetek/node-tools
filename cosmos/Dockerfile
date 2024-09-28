# Builder Image
FROM golang:1.22-bookworm AS builder

ARG GIT_REPOSITORY
ARG IMAGE_TAG

WORKDIR /app

RUN apt-get update && apt-get upgrade -y
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY . && make build


# Node Image create
FROM debian:bookworm-slim

ARG BIN

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -P /usr/lib https://github.com/CosmWasm/wasmvm/releases/download/v2.1.2/libwasmvm.x86_64.so

COPY --from=builder /app/build/${BIN} /usr/bin/${BIN}
COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
