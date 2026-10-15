# syntax=docker/dockerfile:1
# Single image: builds the Vite frontend, then FastAPI serves the API and the built static files.

# ---- Stage 1: build the frontend ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# outputs /web/dist
RUN npm run build

# Docker CLI only. The trusted orchestrator uses it to manage isolated child
# containers; the child containers never receive the engine socket.
FROM docker:27-cli AS docker-cli

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=5 \
    PORT=8000 \
    STATIC_DIR=/app/static \
    SEED_DIR=/app/data \
    DATA_DIR=/var/lib/apc

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Repository scanning needs Git at runtime. Keep this after Python dependencies
# so changing OS packages does not invalidate the slower pip layer.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
ENV HOME=/tmp

COPY backend/ ./
# inventory.yaml, attack_subset.json, samples/ (data/attack is excluded by .dockerignore)
COPY data/ ./data/
COPY --from=web /web/dist ./static

# Writable location for SQLite; run as non-root.
RUN useradd --system --uid 10001 apc && mkdir -p "$DATA_DIR" && chown apc "$DATA_DIR"
USER apc
VOLUME ["/var/lib/apc"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'))"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
