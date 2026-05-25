# syntax=docker/dockerfile:1.7

ARG ALPINE_VERSION=3.23
ARG GO_VERSION=1.25.10
ARG GAIA_VERSION
ARG GIT_REPOSITORY=https://github.com/cosmos/gaia.git
ARG BIN=gaiad
ARG ROCKSDB_VERSION=v10.2.1
ARG ROCKSDB_SO_VERSION=10.2.1
ARG BUILD_TAGS="netgo muslc rocksdb"

FROM golang:${GO_VERSION}-alpine${ALPINE_VERSION} AS build-base

RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache \
    bash \
    bzip2-dev \
    ca-certificates \
    g++ \
    gflags-dev \
    git \
    linux-headers \
    lz4-dev \
    make \
    perl \
    pkgconf \
    snappy-dev \
    wget \
    zlib-dev \
    zstd-dev

FROM build-base AS rocksdb-builder
ARG ROCKSDB_VERSION

WORKDIR /src/rocksdb

RUN git clone --depth 1 --branch "${ROCKSDB_VERSION}" https://github.com/facebook/rocksdb.git . \
  && { \
    grep -q '#include <cstdint>' db/blob/blob_file_meta.h \
      || sed -i '/#include "rocksdb\/rocksdb_namespace.h"/i #include <cstdint>' db/blob/blob_file_meta.h; \
  } \
  && make -j"$(nproc)" shared_lib PORTABLE=1 USE_RTTI=1 \
  && mkdir -p /usr/local/include /usr/local/lib/pkgconfig \
  && cp -a include/rocksdb /usr/local/include/ \
  && cp -a librocksdb.so* /usr/local/lib/ \
  && { \
    echo 'prefix=/usr/local'; \
    echo 'exec_prefix=${prefix}'; \
    echo 'includedir=${prefix}/include'; \
    echo 'libdir=${exec_prefix}/lib'; \
    echo; \
    echo 'Name: rocksdb'; \
    echo 'Description: An embeddable persistent key-value store for fast storage'; \
    echo "Version: ${ROCKSDB_VERSION#v}"; \
    echo 'Libs: -L${libdir} -lrocksdb'; \
    echo 'Libs.private: -lpthread -lrt -ldl -lsnappy -lgflags -lz -lbz2 -llz4 -lzstd'; \
    echo 'Cflags: -I${includedir} -std=c++17'; \
  } > /usr/local/lib/pkgconfig/rocksdb.pc \
  && find /usr/local/lib -maxdepth 1 -type f -name 'librocksdb.so.*' -exec strip --strip-unneeded {} \;

FROM build-base AS gaiad-builder
ARG BUILD_TAGS
ARG GAIA_VERSION
ARG GIT_REPOSITORY
ARG BIN

COPY --from=rocksdb-builder /usr/local/include/rocksdb /usr/local/include/rocksdb
COPY --from=rocksdb-builder /usr/local/lib/librocksdb.so* /usr/local/lib/
COPY --from=rocksdb-builder /usr/local/lib/pkgconfig/rocksdb.pc /usr/local/lib/pkgconfig/rocksdb.pc

ENV CGO_ENABLED=1
ENV CGO_CFLAGS="-I/usr/local/include -D__BLST_PORTABLE__"
ENV CGO_LDFLAGS="-L/usr/local/lib"
ENV LD_LIBRARY_PATH="/usr/local/lib"
ENV PKG_CONFIG_PATH="/usr/local/lib/pkgconfig"
ENV EXTLDFLAGS="-L/usr/local/lib -lrocksdb -lstdc++ -lm -lz -lbz2 -lsnappy -llz4 -lzstd -lgflags"

WORKDIR /src/gaia

RUN : "${GAIA_VERSION:?GAIA_VERSION build arg is required}" \
  && git clone --depth 1 --branch "${GAIA_VERSION}" "${GIT_REPOSITORY}" .

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    set -euxo pipefail; \
    APP_VERSION="$(git describe --exact-match 2>/dev/null || echo "${GAIA_VERSION}")"; \
    COMMIT="$(git rev-parse HEAD)"; \
    TM_VERSION="$(go list -m github.com/cometbft/cometbft | awk '{print $2}')"; \
    WASMVM_VERSION="$(go list -m github.com/CosmWasm/wasmvm/v2 | awk '{print $2}')"; \
    WASMVM_DIR="$(go env GOPATH)/pkg/mod/github.com/!cosm!wasm/wasmvm/v2@${WASMVM_VERSION}"; \
    go mod download github.com/CosmWasm/wasmvm/v2; \
    chmod u+w "${WASMVM_DIR}/internal/api"; \
    wget -O "${WASMVM_DIR}/internal/api/libwasmvm_muslc.x86_64.a" \
      "https://github.com/CosmWasm/wasmvm/releases/download/${WASMVM_VERSION}/libwasmvm_muslc.x86_64.a"; \
    go build \
      -mod=readonly \
      -tags "${BUILD_TAGS}" \
      -ldflags "\
        -X github.com/cosmos/cosmos-sdk/version.Name=gaia \
        -X github.com/cosmos/cosmos-sdk/version.AppName=gaiad \
        -X github.com/cosmos/cosmos-sdk/version.Version=${APP_VERSION} \
        -X github.com/cosmos/cosmos-sdk/version.Commit=${COMMIT} \
        -X github.com/cosmos/cosmos-sdk/version.BuildTags=$(echo "${BUILD_TAGS}" | tr ' ' ',') \
        -X github.com/cometbft/cometbft/version.TMCoreSemVer=${TM_VERSION} \
        -w -s \
        -extldflags '${EXTLDFLAGS}'" \
      -trimpath \
      -o "/out/${BIN}" \
      "./cmd/${BIN}"

FROM alpine:${ALPINE_VERSION} AS runtime
ARG GAIA_VERSION
ARG ROCKSDB_VERSION
ARG ROCKSDB_SO_VERSION
ARG BIN

LABEL org.opencontainers.image.title="Cosmos Gaia with RocksDB" \
      org.opencontainers.image.description="Gaia built with RocksDB support for Cosmos Hub nodes" \
      org.opencontainers.image.source="https://github.com/cosmos/gaia" \
      org.opencontainers.image.version="${GAIA_VERSION}" \
      org.opencontainers.image.vendor="Impulse Expert" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV HOME=/root
ENV LD_LIBRARY_PATH=/usr/local/lib

RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache \
    ca-certificates \
    gflags \
    libbz2 \
    libstdc++ \
    lz4-libs \
    snappy \
    zlib \
    zstd-libs

COPY --from=rocksdb-builder /usr/local/lib/librocksdb.so* /usr/local/lib/
COPY --from=gaiad-builder /out/${BIN} /usr/local/bin/${BIN}

RUN set -eux; \
  test -f "/usr/local/lib/librocksdb.so.${ROCKSDB_SO_VERSION}"; \
  ROCKSDB_ABI_VERSION="${ROCKSDB_SO_VERSION%.*}"; \
  ROCKSDB_MAJOR_VERSION="${ROCKSDB_SO_VERSION%%.*}"; \
  ln -sf "librocksdb.so.${ROCKSDB_SO_VERSION}" "/usr/local/lib/librocksdb.so.${ROCKSDB_ABI_VERSION}"; \
  ln -sf "librocksdb.so.${ROCKSDB_SO_VERSION}" "/usr/local/lib/librocksdb.so.${ROCKSDB_MAJOR_VERSION}"; \
  ln -sf "librocksdb.so.${ROCKSDB_SO_VERSION}" /usr/local/lib/librocksdb.so

EXPOSE 26656 26657 1317 9090

ENTRYPOINT ["gaiad"]
CMD ["version"]
