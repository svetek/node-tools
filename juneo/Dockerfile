# Builder Image
FROM debian:bookworm-slim

ARG BIN
ARG GIT_REPOSITORY
ARG IMAGE_TAG

WORKDIR /app

RUN apt-get update && apt-get upgrade -y && apt-get install git -y
RUN git clone --depth 1 --branch $IMAGE_TAG $GIT_REPOSITORY .
RUN chmod -R +x juneogo ./plugins

ENTRYPOINT [ "./juneogo", "--plugin-dir=./plugins" ]