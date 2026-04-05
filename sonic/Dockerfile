FROM debian:13-slim

ARG IMAGE_TAG
ARG GIT_REPOSITORY=https://github.com/0xsoniclabs/sonic

ARG UID=10001
ARG GID=10001

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /home/appuser

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    test -n "${IMAGE_TAG}"; \
    curl -fsSL -o "/usr/local/bin/sonicd" \
      "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/sonicd"; \
    curl -fsSL -o "/usr/local/bin/sonictool" \
      "${GIT_REPOSITORY}/releases/download/${IMAGE_TAG}/sonictool"; \
    chmod 0755 "/usr/local/bin/sonicd" "/usr/local/bin/sonictool"

RUN set -eux; \
    groupadd --gid "${GID}" appuser; \
    useradd \
      --uid "${UID}" \
      --gid "${GID}" \
      --home-dir /home/appuser \
      --shell /usr/sbin/nologin \
      appuser; \
    install -d -m 0755 -o "${UID}" -g "${GID}" /home/appuser

EXPOSE 18545/tcp 18546/tcp 5050/tcp 5050/udp

USER appuser:appuser

ENTRYPOINT ["sonicd"]