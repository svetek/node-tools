FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY node_rpc_checker ./node_rpc_checker
RUN python -m pip wheel --wheel-dir /wheels .

FROM python:3.12-slim
ARG VERSION
LABEL org.opencontainers.image.title="node-rpc-checker" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/svetek/node-tools"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN adduser --disabled-password --gecos "" appuser
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index /wheels/*.whl
RUN python -c "import os, importlib.metadata; from node_rpc_checker import __version__; assert __version__ == os.environ['VERSION'] == importlib.metadata.version('node-rpc-checker'), 'image/package version mismatch'"
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('HTTP_PORT','8080')+'/healthz', timeout=3)" || exit 1
ENTRYPOINT ["node-rpc-checker"]
