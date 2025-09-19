# Node Image create
FROM debian:bookworm-slim

# Prevent interactive prompts during package installation
ARG DEBIAN_FRONTEND=noninteractive
ARG GIT_REPOSITORY
ARG IMAGE_TAG
ARG BIN

ENV BIN=${BIN}

# Install only minimal dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl wget jq expect procps \
    && rm -rf /var/lib/apt/lists/*

# Download the binary directly from GitHub
RUN curl -fL "${GIT_REPOSITORY}/releases/download/uniond/${IMAGE_TAG}/uniond-release-x86_64-linux" -o "/usr/local/bin/${BIN}" \
 && chmod 0755 "/usr/local/bin/${BIN}"

COPY ./run_node.sh .

RUN chmod +x ./run_node.sh

ENTRYPOINT [ "./run_node.sh" ]