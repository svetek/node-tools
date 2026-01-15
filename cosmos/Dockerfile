FROM debian:bookworm-slim

ARG BIN
ARG GIT_REPOSITORY
ARG IMAGE_TAG

ENV BIN="${BIN}"

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    curl -fsSLo /usr/lib/libwasmvm.x86_64.so "https://github.com/CosmWasm/wasmvm/releases/download/v2.2.4/libwasmvm.x86_64.so"; \
    curl -fsSLo "/usr/bin/${BIN}" "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/${BIN}-${IMAGE_TAG}-linux-amd64"; \
    chmod 0755 "/usr/bin/${BIN}"

ENTRYPOINT [ "gaiad" ]
