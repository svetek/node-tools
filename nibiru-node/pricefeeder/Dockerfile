# Node Image create
FROM debian:bullseye-slim

RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y tzdata ca-certificates curl wget jq \
    && apt-get -y purge && apt-get -y clean \
    && apt-get -y autoremove && rm -rf /var/lib/apt/lists/*

RUN curl -s https://get.nibiru.fi/pricefeeder@v0.21.3! | bash

ENTRYPOINT ["pricefeeder"]
