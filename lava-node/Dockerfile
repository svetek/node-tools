# Node Image create
FROM debian:bookworm-slim

ARG BIN
ARG BUILD_DATE
ARG GIT_REPOSITORY
ARG IMAGE_TAG
ARG NODE_TYPE

LABEL image-tag=$IMAGE_TAG
LABEL build-date=$BUILD_DATE
LABEL node-type=$NODE_TYPE

ENV BIN=$BIN
ENV NODE_TYPE=$NODE_TYPE

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN wget -qO /usr/bin/$BIN "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/${BIN}-${IMAGE_TAG}-linux-amd64" \
    && chmod +x /usr/bin/$BIN

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]
