# Node Image create
FROM debian:bookworm-slim

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN curl -s https://get.nibiru.fi/pricefeeder@v1.0.0! | bash

ENTRYPOINT ["pricefeeder"]
