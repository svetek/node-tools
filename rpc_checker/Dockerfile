FROM python:3.12-slim
ARG VERSION=1.1.0
LABEL org.opencontainers.image.title="rpc-checker" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/svetek/node-tools"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN adduser --disabled-password --gecos "" appuser
COPY rpc_checker ./rpc_checker
RUN python -c "import os; from rpc_checker import __version__; assert __version__ == os.environ['VERSION'], 'image/package version mismatch'"
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('HTTP_PORT','8080')+'/healthz', timeout=3)" || exit 1
CMD ["python", "-m", "rpc_checker"]
