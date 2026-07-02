# syntax=docker/dockerfile:1.7

ARG DEBIAN_VERSION=trixie
ARG RUST_VERSION=1.91.0
ARG IMAGE_TAG
ARG GIT_REPOSITORY=https://github.com/casper-network/casper-node-launcher.git
ARG BIN=casper-node-launcher

FROM rust:${RUST_VERSION}-${DEBIAN_VERSION} AS casper-node-launcher-builder
ARG IMAGE_TAG
ARG GIT_REPOSITORY
ARG BIN

WORKDIR /src/casper-node-launcher

RUN git clone --depth 1 --branch "${IMAGE_TAG:?IMAGE_TAG build arg is required}" "${GIT_REPOSITORY}" .

RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/usr/local/cargo/git \
    --mount=type=cache,target=/src/casper-node-launcher/target \
    set -eux; \
    cargo build --release; \
    install -Dm0755 "target/release/${BIN}" "/out/${BIN}"

FROM debian:${DEBIAN_VERSION}-slim AS runtime
ARG IMAGE_TAG

LABEL org.opencontainers.image.title="Casper Node Launcher" \
      org.opencontainers.image.description="casper-node-launcher built from source, runs and upgrades casper-node across protocol versions" \
      org.opencontainers.image.source="https://github.com/casper-network/casper-node-launcher" \
      org.opencontainers.image.version="${IMAGE_TAG}" \
      org.opencontainers.image.vendor="Impulse Expert" \
      org.opencontainers.image.licenses="Apache-2.0"

RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libssl3t64 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=casper-node-launcher-builder /out/casper-node-launcher /usr/bin/casper-node-launcher

EXPOSE 35000 7779 8888 9999

ENTRYPOINT ["/usr/bin/casper-node-launcher"]
