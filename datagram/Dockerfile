FROM debian:bookworm-slim

# Prevent interactive prompts during package installation
ARG DEBIAN_FRONTEND=noninteractive
ARG GIT_REPOSITORY
ARG IMAGE_TAG
ARG BIN

# Install only minimal dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget \
  && rm -rf /var/lib/apt/lists/*

# Download the binary directly from GitHub
RUN wget -q "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/datagram-cli-x86_64-linux" \
      -O "/usr/local/bin/${BIN}" \
  && chmod 0755 "/usr/local/bin/${BIN}"

# # Switch to non-root user
RUN useradd -m -u 1001 -r -s /usr/sbin/nologin appuser
USER appuser

# # Entrypoint and default command
ENTRYPOINT ["datagram"]
