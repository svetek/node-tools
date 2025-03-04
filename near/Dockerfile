# Builder Image
FROM rust:slim-bookworm AS builder

ARG GIT_REPOSITORY
ARG IMAGE_TAG
ARG RUST_VERSION=1.84.0

# Set Working Directory is /app
WORKDIR /app

# Install dependencies
RUN apt-get update -qq && apt-get install -y git cmake clang llvm pkg-config g++ libssl-dev libclang-dev curl

# Install Rust 1.84.0
RUN rustup install ${RUST_VERSION} && rustup default ${RUST_VERSION}

# Clone and build the project
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY .
RUN make release

# Production Image
FROM debian:bookworm-slim

ARG BIN

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect procps \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*
 
COPY --from=builder /app/target/release/$BIN /usr/bin/$BIN
COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
