FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY evm_height_checker ./evm_height_checker
COPY pyproject.toml ./pyproject.toml

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,sys,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"HTTP_PORT\", \"8080\")}/readyz', timeout=3); sys.exit(0)" || exit 1

CMD ["python", "-m", "evm_height_checker"]
