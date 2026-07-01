FROM debian:13-slim

ARG IMAGE_TAG
ARG XRPLD_REPO_BASE=https://repos.ripple.com/repos/rippled-deb
ARG OS_CODENAME=trixie
ARG XRPLD_CHANNEL=stable
ARG XRPLD_PACKAGE_NAMES="xrpld"
ARG XRPLD_UID=10001
ARG XRPLD_GID=10001

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg wget; \
    install -m 0755 -d /etc/apt/keyrings; \
    wget -qO /tmp/xrpld.key "https://repos.ripple.com/repos/api/gpg/key/public"; \
    test "$(gpg --show-keys --with-colons /tmp/xrpld.key | awk -F: '$1 == "fpr" {print $10; exit}')" = "E057C1CF72B0DF1A4559E8577DEE9236AB06FAA6"; \
    gpg --dearmor -o /etc/apt/keyrings/xrpld.gpg /tmp/xrpld.key; \
    printf '%s\n' \
      'Types: deb' \
      "URIs: ${XRPLD_REPO_BASE}" \
      "Suites: ${OS_CODENAME}" \
      "Components: ${XRPLD_CHANNEL}" \
      'Signed-By: /etc/apt/keyrings/xrpld.gpg' \
      > /etc/apt/sources.list.d/xrpld.sources; \
    apt-get update; \
    XRPLD_PACKAGE_NAME=""; \
    XRPLD_VERSION=""; \
    for candidate in ${XRPLD_PACKAGE_NAMES}; do \
      version="$(apt-cache madison "${candidate}" | awk -v tag="${IMAGE_TAG}" '$3 ~ "^" tag {print $3; exit}')"; \
      if [ -n "${version}" ]; then \
        XRPLD_PACKAGE_NAME="${candidate}"; \
        XRPLD_VERSION="${version}"; \
        break; \
      fi; \
    done; \
    test -n "${XRPLD_PACKAGE_NAME}"; \
    test -n "${XRPLD_VERSION}"; \
    apt-get install -y --no-install-recommends "${XRPLD_PACKAGE_NAME}=${XRPLD_VERSION}"; \
    apt-get purge -y --auto-remove gnupg wget; \
    rm -f /tmp/xrpld.key; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    groupadd --gid "${XRPLD_GID}" appuser; \
    useradd --uid "${XRPLD_UID}" --gid "${XRPLD_GID}" --home-dir /xrpld/data --shell /usr/sbin/nologin appuser; \
    install -d -m 0755 -o "${XRPLD_UID}" -g "${XRPLD_GID}" /xrpld/data /xrpld/data/nudb; \
    install -d -m 0755 /xrpld/config

EXPOSE 5005 5006 5007 6006 51235

USER appuser:appuser

ENTRYPOINT ["xrpld"]
CMD ["--conf=/xrpld/config/xrpld.cfg", "--fg"]
