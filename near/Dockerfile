# Builder Image
FROM rust:slim-bookworm AS builder

ARG GIT_REPOSITORY
ARG IMAGE_TAG

# Set Working Directory is /app
WORKDIR /app

# Node project build
RUN apt-get update -qq && apt-get install git cmake clang llvm pkg-config g++ libssl-dev libclang-dev -y
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
