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

# Switch to non-root user
RUN useradd -m -u 1001 -r -s /usr/sbin/nologin appuser

COPY --chown=appuser:appuser ./run_node.sh .
RUN chmod +x ./run_node.sh

EXPOSE 26657 9090 1317

USER appuser

ENTRYPOINT [ "./run_node.sh" ]