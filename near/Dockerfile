# Builder image
FROM rust:1.93.0-slim-trixie AS builder

ARG GIT_REPOSITORY=https://github.com/near/nearcore
ARG IMAGE_TAG
ARG RUST_VERSION=1.93.0

WORKDIR /app

RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends \
        git \
        cmake \
        clang \
        llvm \
        pkg-config \
        g++ \
        libssl-dev \
        libclang-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN rustup install ${RUST_VERSION} && rustup default ${RUST_VERSION}

RUN git clone --depth 1 --branch "$IMAGE_TAG" "$GIT_REPOSITORY" .
RUN make release

# Runtime image
FROM debian:trixie-slim

ARG BIN=neard

ENV BIN=$BIN
ENV CONFIG_PATH=/root/.near

WORKDIR /opt/near

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
 
COPY --from=builder /app/target/release/$BIN /usr/bin/$BIN
COPY --chmod=755 ./run_node.sh /usr/local/bin/run_node.sh

ENTRYPOINT ["/usr/local/bin/run_node.sh"]
