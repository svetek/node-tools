# --- Builder stage ---
FROM golang:1.24-bookworm AS builder

ARG GIT_REPOSITORY
ARG IMAGE_TAG
ARG BIN

ENV DEBIAN_FRONTEND=noninteractive

# Install required system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential gcc git jq pkg-config curl clang \
        mesa-opencl-icd ocl-icd-opencl-dev hwloc libhwloc-dev wget ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:$PATH"

# Set compiler flags
ENV RUSTFLAGS="-C target-cpu=native -g"
ENV CGO_CFLAGS_ALLOW="-D__BLST_PORTABLE__"
ENV CGO_CFLAGS="-D__BLST_PORTABLE__"
ENV FFI_BUILD_FROM_SOURCE=1

# Clone Lotus and build the main binary
WORKDIR /app
RUN git clone --depth 1 --branch ${IMAGE_TAG} ${GIT_REPOSITORY} . && \
    make clean && \
    make ${BIN}


# --- Runtime stage ---
FROM debian:bookworm-slim AS runtime

ARG BIN

ENV BIN=$BIN

# Install required system dependencies
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect libhwloc15 hwloc\
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

# Copy binary from builder
COPY --from=builder /app/${BIN} /usr/bin/${BIN}

EXPOSE 1234 1235

ENTRYPOINT ["lotus"]
