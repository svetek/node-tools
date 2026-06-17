# syntax=docker/dockerfile:1.7

ARG ALPINE_VERSION=3.23
ARG GO_VERSION=1.25.10
ARG IMAGE_TAG
ARG AXELAR_VERSION
ARG GIT_REPOSITORY=https://github.com/axelarnetwork/axelar-core.git
ARG BIN=axelard
ARG WASM=true
ARG IBC_WASM_HOOKS=false

FROM golang:${GO_VERSION}-alpine${ALPINE_VERSION} AS build-base

RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache \
    bash \
    build-base \
    ca-certificates \
    git \
    linux-headers \
    make \
    wget

FROM build-base AS axelard-builder
ARG IMAGE_TAG
ARG AXELAR_VERSION
ARG GIT_REPOSITORY
ARG BIN
ARG WASM
ARG IBC_WASM_HOOKS
ARG TARGETARCH

ENV CGO_ENABLED=1

WORKDIR /src/axelar

RUN AXELAR_RELEASE="${AXELAR_VERSION:-${IMAGE_TAG:?IMAGE_TAG build arg is required}}" \
  && git clone --depth 1 --branch "${AXELAR_RELEASE}" "${GIT_REPOSITORY}" .

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    set -eux; \
    go mod download; \
    if [ "${WASM}" = "true" ]; then \
      case "${TARGETARCH:-amd64}" in \
        amd64) AXELAR_ARCH="x86_64" ;; \
        arm64) AXELAR_ARCH="aarch64" ;; \
        *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
      esac; \
      WASMVM_VERSION="$(go list -m github.com/CosmWasm/wasmvm/v2 | awk '{print $2}')"; \
      wget -O "/lib/libwasmvm_muslc.${AXELAR_ARCH}.a" \
        "https://github.com/CosmWasm/wasmvm/releases/download/${WASMVM_VERSION}/libwasmvm_muslc.${AXELAR_ARCH}.a"; \
      wget -O /tmp/wasmvm-checksums.txt \
        "https://github.com/CosmWasm/wasmvm/releases/download/${WASMVM_VERSION}/checksums.txt"; \
      EXPECTED_SHA256="$(grep "libwasmvm_muslc.${AXELAR_ARCH}.a" /tmp/wasmvm-checksums.txt | awk '{print $1}')"; \
      echo "${EXPECTED_SHA256}  /lib/libwasmvm_muslc.${AXELAR_ARCH}.a" | sha256sum -c -; \
    fi; \
    case "${TARGETARCH:-amd64}" in \
      amd64) AXELAR_ARCH="x86_64" ;; \
      arm64) AXELAR_ARCH="aarch64" ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    make \
      ARCH="${AXELAR_ARCH}" \
      MUSLC="${WASM}" \
      WASM="${WASM}" \
      IBC_WASM_HOOKS="${IBC_WASM_HOOKS}" \
      build; \
    test -x "./bin/${BIN}"

FROM alpine:${ALPINE_VERSION} AS runtime
ARG IMAGE_TAG
ARG AXELAR_VERSION
ARG BIN

LABEL org.opencontainers.image.title="Axelar" \
      org.opencontainers.image.description="Axelar Core binary built from source" \
      org.opencontainers.image.source="https://github.com/axelarnetwork/axelar-core" \
      org.opencontainers.image.version="${IMAGE_TAG}" \
      org.opencontainers.image.vendor="Impulse Expert" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV HOME=/root

RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache ca-certificates

COPY --chmod=0755 --from=axelard-builder /src/axelar/bin/${BIN} /usr/local/bin/${BIN}

EXPOSE 26656 26657 1317 9090

ENTRYPOINT ["axelard"]
CMD ["version"]
