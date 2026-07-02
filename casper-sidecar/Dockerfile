# syntax=docker/dockerfile:1.7

ARG DEBIAN_VERSION=trixie
ARG RUST_VERSION=1.91.0
ARG IMAGE_TAG
ARG GIT_REPOSITORY=https://github.com/casper-network/casper-sidecar.git
ARG BIN=casper-sidecar

FROM rust:${RUST_VERSION}-${DEBIAN_VERSION} AS casper-sidecar-builder
ARG IMAGE_TAG
ARG GIT_REPOSITORY
ARG BIN

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src/casper-sidecar

RUN git clone --depth 1 --branch "${IMAGE_TAG:?IMAGE_TAG build arg is required}" "${GIT_REPOSITORY}" .

RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/src/casper-sidecar/target \
    set -eux; \
    cargo build --release -p casper-sidecar; \
    install -Dm0755 "target/release/${BIN}" "/out/${BIN}"

FROM debian:${DEBIAN_VERSION}-slim AS runtime
ARG IMAGE_TAG

LABEL org.opencontainers.image.title="Casper Sidecar" \
      org.opencontainers.image.description="casper-sidecar built from source, serves the JSON-RPC/REST/SSE APIs backed by a local casper-node" \
      org.opencontainers.image.source="https://github.com/casper-network/casper-sidecar" \
      org.opencontainers.image.version="${IMAGE_TAG}" \
      org.opencontainers.image.vendor="Impulse Expert" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libssl3t64 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=casper-sidecar-builder /out/casper-sidecar /usr/bin/casper-sidecar

EXPOSE 7777

ENTRYPOINT ["/usr/bin/casper-sidecar"]
