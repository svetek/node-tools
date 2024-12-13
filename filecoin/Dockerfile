# Builder Image
FROM golang:1.23-bookworm AS builder

ARG GIT_REPOSITORY
ARG IMAGE_TAG

ENV FIL_PROOFS_USE_GPU_COLUMN_BUILDER=1
ENV FIL_PROOFS_USE_GPU_TREE_BUILDER=1
ENV FIL_PROOFS_GPU_MODE=1
ENV RUST_GPU_TOOLS_CUSTOM_GPU="NVIDIA RTX A5000:8192"

WORKDIR /app

RUN apt-get update && apt-get upgrade -y
RUN apt-get install mesa-opencl-icd ocl-icd-opencl-dev gcc git bzr jq pkg-config curl clang build-essential hwloc libhwloc-dev wget -y
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
ENTRYPOINT [ "/bin/${BIN}" ]