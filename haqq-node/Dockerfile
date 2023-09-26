# Node Image create
FROM debian:bullseye-slim

ARG IMAGE_TAG
ARG BUILD_DATE
LABEL image-tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -qO- "https://github.com/haqq-network/haqq/releases/download/${IMAGE_TAG}/haqq_${IMAGE_TAG#v}_Linux_x86_64.tar.gz" | tar xz --strip-components=1 -C /usr/bin/

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "/bin/bash", "/run_node.sh" ]
