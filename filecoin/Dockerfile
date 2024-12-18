# Builder Image
FROM golang:1.23-bookworm AS builder

ARG GIT_REPOSITORY
ARG IMAGE_TAG

ENV FIL_PROOFS_USE_GPU_COLUMN_BUILDER=1
ENV FIL_PROOFS_USE_GPU_TREE_BUILDER=1
ENV FIL_PROOFS_GPU_MODE=1
ENV FFI_PORTABLE=1
ENV FFI_BUILD_FROM_SOURCE=1
ENV FFI_USE_CUDA=1
ENV RUST_GPU_TOOLS_CUSTOM_GPU="NVIDIA RTX A5000:8192"

ENV XDG_CACHE_HOME="/tmp"
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=/usr/local/cargo/bin:$PATH
ENV RUST_VERSION=1.63.0
ENV RUSTFLAGS="-C target-cpu=native -g"

ENV CGO_CFLAGS_ALLOW="-D__BLST_PORTABLE__"
ENV CGO_CFLAGS="-D__BLST_PORTABLE__"


WORKDIR /app

RUN apt-get update && apt-get upgrade -y
RUN apt-get install mesa-opencl-icd ocl-icd-opencl-dev gcc git bzr jq pkg-config curl clang build-essential hwloc libhwloc-dev wget ca-certificates ocl-icd-libopencl1 jq libhwloc-dev -y

RUN set -eux; \
    dpkgArch="$(dpkg --print-architecture)"; \
    case "${dpkgArch##*-}" in \
        amd64) rustArch='x86_64-unknown-linux-gnu'; rustupSha256='5cc9ffd1026e82e7fb2eec2121ad71f4b0f044e88bca39207b3f6b769aaa799c' ;; \
        arm64) rustArch='aarch64-unknown-linux-gnu'; rustupSha256='e189948e396d47254103a49c987e7fb0e5dd8e34b200aa4481ecc4b8e41fb929' ;; \
        *) echo >&2 "unsupported architecture: ${dpkgArch}"; exit 1 ;; \
    esac; \
    url="https://static.rust-lang.org/rustup/archive/1.25.1/${rustArch}/rustup-init"; \
    wget "$url"; \
    echo "${rustupSha256} *rustup-init" | sha256sum -c -; \
    chmod +x rustup-init; \
    ./rustup-init -y --no-modify-path --profile minimal --default-toolchain $RUST_VERSION --default-host ${rustArch}; \
    rm rustup-init; \
    chmod -R a+w $RUSTUP_HOME $CARGO_HOME; \
    rustup --version; \
    cargo --version; \
    rustc --version;

RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY . && make clean all && make build


# Node Image create
FROM nvidia/cuda:12.6.2-cudnn-runtime-ubuntu24.04

ARG BIN
ARG IMAGE_TAG

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect libhwloc15 hwloc\
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -P /usr/lib https://github.com/CosmWasm/wasmvm/releases/download/v1.3.1/libwasmvm.x86_64.so
#RUN cd /tmp \
#    && curl -Lo -  https://github.com/filecoin-project/lotus/releases/download/$IMAGE_TAG/lotus_${IMAGE_TAG}_linux_amd64_v1.tar.gz | tar zxv \
#    && mv lotus* ${BIN} \
#    && mv ${BIN}/${BIN} /bin/

COPY --from=builder /app/${BIN} /usr/bin/${BIN}
COPY --from=builder /app/${BIN}* /usr/bin/
RUN chmod +x /bin/${BIN}
#COPY ./run_node.sh .

#RUN chmod +x ./run_node.sh

#ENTRYPOINT [ "./run_node.sh" ]
ENTRYPOINT [ "/bin/lotus" ]