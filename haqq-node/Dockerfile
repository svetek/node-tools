# Node Image create
FROM debian:bookworm-slim

ARG IMAGE_TAG
ARG BUILD_DATE
ARG BIN

LABEL image-tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE

ENV BIN=$BIN

WORKDIR /app

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq expect \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -O haqq_${IMAGE_TAG#v}_Linux_x86_64.tar.gz "https://github.com/haqq-network/haqq/releases/download/${IMAGE_TAG}/haqq_${IMAGE_TAG#v}_Linux_x86_64.tar.gz" \
    && tar xfz haqq_${IMAGE_TAG#v}_Linux_x86_64.tar.gz -C /usr bin/haqqd \
    && rm -rf *

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
