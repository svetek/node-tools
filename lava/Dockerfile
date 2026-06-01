# syntax=docker/dockerfile:1.7

ARG ALPINE_VERSION=3.23
ARG BUILDER_ALPINE_VERSION=3.20
ARG GO_VERSION=1.23.3
ARG LAVA_VERSION=v6.0.0
ARG GIT_REPOSITORY=https://github.com/lavanet/lava.git
ARG BIN=lavad
ARG ROCKSDB_VERSION=v7.10.2
ARG ROCKSDB_SO_VERSION=7.10.2

FROM golang:${GO_VERSION}-alpine${BUILDER_ALPINE_VERSION} AS build-base

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
    grep -q '#include <cstdint>' table/block_based/data_block_hash_index.h \
      || sed -i '/#include "rocksdb\/slice.h"/i #include <cstdint>' table/block_based/data_block_hash_index.h; \
    grep -q '#include <cstdint>' util/string_util.h \
      || sed -i '/#include "rocksdb\/rocksdb_namespace.h"/i #include <cstdint>' util/string_util.h; \
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

FROM build-base AS lava-builder
ARG LAVA_VERSION
ARG GIT_REPOSITORY
ARG BIN

COPY --from=rocksdb-builder /usr/local/include/rocksdb /usr/local/include/rocksdb
COPY --from=rocksdb-builder /usr/local/lib/librocksdb.so* /usr/local/lib/
COPY --from=rocksdb-builder /usr/local/lib/pkgconfig/rocksdb.pc /usr/local/lib/pkgconfig/rocksdb.pc

ENV CGO_ENABLED=1
ENV CGO_CFLAGS="-I/usr/local/include -D__BLST_PORTABLE__"
ENV CGO_LDFLAGS="-L/usr/local/lib -lrocksdb -lstdc++ -lm -lz -lbz2 -lsnappy -llz4 -lzstd -lgflags"
ENV LD_LIBRARY_PATH="/usr/local/lib"
ENV PKG_CONFIG_PATH="/usr/local/lib/pkgconfig"

WORKDIR /src/lava

RUN : "${BIN:?BIN build arg is required}" \
  && : "${LAVA_VERSION:?LAVA_VERSION build arg is required}" \
  && git clone --depth 1 --branch "${LAVA_VERSION}" "${GIT_REPOSITORY}" .

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    make build-"${BIN}" \
      LAVA_BINARY="${BIN}" \
      LAVA_BUILD_OPTIONS="rocksdb release" \
      BUILD_TAGS="rocksdb" \
      LEDGER_ENABLED=false

FROM alpine:${ALPINE_VERSION} AS runtime
ARG LAVA_VERSION
ARG ROCKSDB_SO_VERSION
ARG BIN

LABEL org.opencontainers.image.title="Lava with RocksDB" \
      org.opencontainers.image.description="Lava binary built from source with RocksDB backend support" \
      org.opencontainers.image.source="https://github.com/lavanet/lava" \
      org.opencontainers.image.version="${LAVA_VERSION}" \
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

COPY --from=rocksdb-builder /usr/local/lib/librocksdb.so.${ROCKSDB_SO_VERSION} /usr/local/lib/
COPY --chmod=0755 --from=lava-builder /src/lava/build/${BIN} /usr/local/bin/${BIN}

RUN set -eux; \
  test -f "/usr/local/lib/librocksdb.so.${ROCKSDB_SO_VERSION}"; \
  ROCKSDB_ABI_VERSION="${ROCKSDB_SO_VERSION%.*}"; \
  ROCKSDB_MAJOR_VERSION="${ROCKSDB_SO_VERSION%%.*}"; \
  ln -sf "librocksdb.so.${ROCKSDB_SO_VERSION}" "/usr/local/lib/librocksdb.so.${ROCKSDB_ABI_VERSION}"; \
  ln -sf "librocksdb.so.${ROCKSDB_SO_VERSION}" "/usr/local/lib/librocksdb.so.${ROCKSDB_MAJOR_VERSION}"; \
  ln -sf "librocksdb.so.${ROCKSDB_SO_VERSION}" /usr/local/lib/librocksdb.so

EXPOSE 26656 26657 1317 9090

ENTRYPOINT ["lavad"]
CMD ["version"]
