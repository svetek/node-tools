# syntax=docker/dockerfile:1.7

ARG UBUNTU_VERSION=24.04
ARG IMAGE_TAG
ARG HL_CHAIN=Mainnet
ARG HL_USER=hluser
ARG HL_UID=10001
ARG HL_GID=10001
ARG HL_PUB_KEY_URL=https://raw.githubusercontent.com/hyperliquid-dex/node/refs/heads/main/pub_key.asc
ARG GIT_REPOSITORY=https://github.com/hyperliquid-dex/node
ARG BIN=hl-visor

FROM ubuntu:${UBUNTU_VERSION} AS runtime
ARG IMAGE_TAG
ARG HL_CHAIN
ARG HL_USER
ARG HL_UID
ARG HL_GID
ARG HL_PUB_KEY_URL

LABEL org.opencontainers.image.title="Hyperliquid node" \
      org.opencontainers.image.description="Hyperliquid hl-visor (non-validator / HyperEVM JSON-RPC) on Ubuntu 24.04 with a data pruner" \
      org.opencontainers.image.source="https://github.com/hyperliquid-dex/node" \
      org.opencontainers.image.version="${IMAGE_TAG}" \
      org.opencontainers.image.vendor="Impulse Expert" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    groupadd --gid "${HL_GID}" "${HL_USER}"; \
    useradd --uid "${HL_UID}" --gid "${HL_GID}" --create-home --home-dir "/home/${HL_USER}" "${HL_USER}"; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        jq; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p "/home/${HL_USER}/hl/data" "/home/${HL_USER}/hl/hyperliquid_data"; \
    chown -R "${HL_UID}:${HL_GID}" "/home/${HL_USER}"

COPY prune.sh /usr/local/bin/hl-prune.sh
RUN chmod 0755 /usr/local/bin/hl-prune.sh

USER ${HL_USER}
WORKDIR /home/${HL_USER}
ENV HOME=/home/${HL_USER}

RUN set -eux; \
    case "${HL_CHAIN}" in \
      Mainnet) HL_BINARIES_URL="https://binaries.hyperliquid.xyz/Mainnet" ;; \
      Testnet) HL_BINARIES_URL="https://binaries.hyperliquid-testnet.xyz/Testnet" ;; \
      *) echo "HL_CHAIN must be Mainnet or Testnet, got '${HL_CHAIN}'" >&2; exit 1 ;; \
    esac; \
    printf '{"chain": "%s"}\n' "${HL_CHAIN}" > "${HOME}/visor.json"; \
    curl -fsSL -o "${HOME}/pub_key.asc" "${HL_PUB_KEY_URL}"; \
    gpg --import "${HOME}/pub_key.asc"; \
    curl -fsSL -o "${HOME}/hl-visor" "${HL_BINARIES_URL}/hl-visor"; \
    curl -fsSL -o "${HOME}/hl-visor.asc" "${HL_BINARIES_URL}/hl-visor.asc"; \
    gpg --verify "${HOME}/hl-visor.asc" "${HOME}/hl-visor"; \
    chmod 0755 "${HOME}/hl-visor"

EXPOSE 3001 4000-4010

ENTRYPOINT ["/home/hluser/hl-visor"]
CMD ["run-non-validator"]
