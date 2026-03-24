FROM debian:13-slim

ARG IMAGE_TAG
ARG RIPPLED_REPO_BASE=https://repos.ripple.com/repos/rippled-deb
ARG OS_CODENAME=trixie
ARG RIPPLED_CHANNEL=stable
ARG RIPPLED_PACKAGE_NAME=rippled
ARG RIPPLED_UID=10001
ARG RIPPLED_GID=10001

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg wget; \
    install -m 0755 -d /etc/apt/keyrings; \
    wget -qO /tmp/ripple.key "https://repos.ripple.com/repos/api/gpg/key/public"; \
    test "$(gpg --show-keys --with-colons /tmp/ripple.key | awk -F: '$1 == "fpr" {print $10; exit}')" = "E057C1CF72B0DF1A4559E8577DEE9236AB06FAA6"; \
    gpg --dearmor -o /etc/apt/keyrings/ripple.gpg /tmp/ripple.key; \
    printf '%s\n' \
      'Types: deb' \
      "URIs: ${RIPPLED_REPO_BASE}" \
      "Suites: ${OS_CODENAME}" \
      "Components: ${RIPPLED_CHANNEL}" \
      'Signed-By: /etc/apt/keyrings/ripple.gpg' \
      > /etc/apt/sources.list.d/ripple.sources; \
    apt-get update; \
    RIPPLED_VERSION="$(apt-cache madison "${RIPPLED_PACKAGE_NAME}" | awk '$3 ~ "^" ENVIRON["IMAGE_TAG"] {print $3; exit}')"; \
    test -n "${RIPPLED_VERSION}"; \
    apt-get install -y --no-install-recommends "${RIPPLED_PACKAGE_NAME}=${RIPPLED_VERSION}"; \
    apt-get purge -y --auto-remove gnupg wget; \
    rm -f /tmp/ripple.key; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    groupadd --gid "${RIPPLED_GID}" appuser; \
    useradd --uid "${RIPPLED_UID}" --gid "${RIPPLED_GID}" --home-dir /rippled/data --shell /usr/sbin/nologin appuser; \
    install -d -m 0755 -o "${RIPPLED_UID}" -g "${RIPPLED_GID}" /rippled/data /rippled/data/nudb; \
    install -d -m 0755 /rippled/config

EXPOSE 5005 5006 5007 6006 51235

USER appuser:appuser

ENTRYPOINT ["rippled"]
CMD ["--conf=/rippled/config/rippled.cfg", "--fg"]
