# syntax=docker/dockerfile:1.7
# Rahat: one image with the API, the built frontend, the job worker and the mock services.
# Prototype. Not an official service. All identity, payment and data services are simulated.

# ---- Stage 1: build the frontend (generated API types are committed, no Python needed)
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: runtime
FROM python:3.12-slim AS app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-urd libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /uvx /usr/local/bin/

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin rahat \
 && mkdir -p /app/backend/var /app/frontend /app/data \
 && chown -R 1000:1000 /app
USER 1000:1000
WORKDIR /app/backend

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/.venv/bin:${PATH}"

# Dependency layer first, so source edits do not reinstall packages.
COPY --chown=1000:1000 backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=1000:1000 backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web --chown=1000:1000 /web/dist /app/frontend/dist
COPY --chown=1000:1000 deploy/start.sh /app/start.sh
# data/ may not exist yet: copy it only if present (BuildKit bind mount, never fails).
RUN --mount=type=bind,target=/ctx \
    if [ -d /ctx/data ]; then cp -r /ctx/data/. /app/data/; fi

ENV APP_ENV=demo \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

CMD ["sh", "/app/start.sh"]
