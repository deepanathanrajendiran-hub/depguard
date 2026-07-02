# DepGuard demo image (docs/HANDOFF_D8-D14.md §D11). The frozen corpus is BAKED IN, so the
# container needs no network and no API key to serve verifiable verdicts.
FROM python:3.12-slim

WORKDIR /app

# Dependency install as its own layer (cache-friendly): metadata + package, then corpus/schemas.
COPY pyproject.toml README.md ./
COPY depguard ./depguard
COPY schemas ./schemas
COPY corpus ./corpus
RUN pip install --no-cache-dir ".[demo]"

# Cloud Run provides $PORT (default 8080). Bind all interfaces.
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn depguard.webapp:app --host 0.0.0.0 --port ${PORT}"]
