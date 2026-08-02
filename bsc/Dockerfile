# syntax=docker/dockerfile:1.7

ARG ALPINE_VERSION=3.24
ARG GO_VERSION=1.26.5
ARG IMAGE_TAG
ARG GIT_REPOSITORY=https://github.com/bnb-chain/bsc.git
ARG BIN=geth

FROM golang:${GO_VERSION}-alpine${ALPINE_VERSION} AS builder

ARG IMAGE_TAG
ARG GIT_REPOSITORY
ARG BIN

RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache \
    bash \
    build-base \
    ca-certificates \
    cmake \
    git \
    linux-headers \
    make \
    musl-dev

WORKDIR /src/bsc

ENV CGO_CFLAGS="-O -D__BLST_PORTABLE__"
ENV CGO_CFLAGS_ALLOW="-O -D__BLST_PORTABLE__"

RUN BSC_RELEASE="${IMAGE_TAG:?IMAGE_TAG build arg is required}" \
    && git clone --depth 1 --branch "${BSC_RELEASE}" "${GIT_REPOSITORY}" .

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    set -eux; \
    go mod download; \
    go run build/ci.go install -static "./cmd/${BIN}"; \
    test -x "build/bin/${BIN}"

FROM alpine:${ALPINE_VERSION} AS runtime

ARG IMAGE_TAG
ARG BIN
ARG UID=1000
ARG GID=1000
ARG BSC_HOME=/bsc
ARG DATA_DIR=/data

LABEL org.opencontainers.image.title="BNB Smart Chain" \
      org.opencontainers.image.description="BNB Smart Chain client built from source" \
      org.opencontainers.image.source="https://github.com/bnb-chain/bsc" \
      org.opencontainers.image.version="${IMAGE_TAG}" \
      org.opencontainers.image.vendor="Impulse Expert" \
      org.opencontainers.image.licenses="GPL-3.0"

ENV HOME=${BSC_HOME}
ENV BSC_HOME=${BSC_HOME}
ENV DATA_DIR=${DATA_DIR}

WORKDIR ${BSC_HOME}

RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache \
    bash \
    ca-certificates \
    tini \
    && addgroup -g "${GID}" bsc \
    && adduser -u "${UID}" -G bsc --shell /sbin/nologin --no-create-home -D bsc \
    && install -d -m 0755 -o "${UID}" -g "${GID}" "${BSC_HOME}" "${DATA_DIR}"

COPY --from=builder --chmod=0755 /src/bsc/build/bin/${BIN} /usr/local/bin/${BIN}

VOLUME ${DATA_DIR}

EXPOSE 8545 8546 8547 30311 30311/udp

USER bsc:bsc

ENTRYPOINT ["/sbin/tini", "--", "geth"]
CMD ["version"]
