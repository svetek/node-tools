# Node Image create
FROM debian:bookworm-slim

ARG BIN
ARG BUILD_DATE
ARG IMAGE_TAG
ARG GIT_REPOSITORY

LABEL image-tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

ENV BIN=$BIN

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -qO - "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/osmosisd-${IMAGE_TAG#v}-linux-amd64.tar.gz" | tar xz -C /usr/bin --wildcards --no-anchored "*$BIN*"

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
