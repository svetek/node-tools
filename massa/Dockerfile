# Builder Image
FROM rust:slim-bookworm AS builder

ARG GIT_REPOSITORY
ARG IMAGE_TAG

# Set Working Directory is /app
WORKDIR /app

# Node project build
RUN apt-get update -qq && apt-get install git cmake clang llvm pkg-config g++ libssl-dev libclang-dev -y
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY .
RUN cargo build --release --bin massa-node --bin massa-client

# Production Image
FROM debian:bookworm-slim

ARG BIN
ARG IMAGE_TAG

ENV BIN=$BIN

WORKDIR /app

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*
 
COPY --from=builder /app/massa-client/config /source/massa-client/config
COPY --from=builder /app/massa-client/base_config /source/massa-client/base_config
COPY --from=builder /app/target/release/massa-client /source/massa-client

COPY --from=builder /app/massa-node/config /source/massa-node/config
COPY --from=builder /app/massa-node/base_config /source/massa-node/base_config
COPY --from=builder /app/massa-node/storage /source/massa-node/storage
COPY --from=builder /app/target/release/massa-node /source/massa-node

RUN echo "{\n\t\"version\":\"$IMAGE_TAG\"\n}" > /source/version.json

COPY run_node.sh /

EXPOSE 31244 31245

ENTRYPOINT [ "/bin/bash", "/run_node.sh" ]