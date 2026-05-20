# Multi-service Dockerfile for the backend monorepo.
# Build target is selected via the SERVICE build arg.
#
# Example:
#   docker build --build-arg SERVICE=auth-service -t auth-service .

FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies for packages that may need compilation
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY packages/ packages/

ARG SERVICE
RUN uv sync --package ${SERVICE} --no-dev

# Final stage — minimal runtime image
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime dependencies:
#   libpq5   — asyncpg (PostgreSQL driver)
#   curl     — healthcheck probing
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/pyproject.toml ./
COPY --from=builder /app/packages/ packages/

ENV PATH="/app/.venv/bin:$PATH"

ARG SERVICE

# Generate a startup script to avoid bash-only ${SERVICE//-/_} substitution.
# `tr - _` is POSIX-compatible and works under /bin/sh (dash).
RUN printf '#!/bin/sh\nset -e\nuvicorn %s.main:app --host 0.0.0.0 --port 8000\n' \
      "$(echo ${SERVICE} | tr - _)" > /app/start.sh \
    && chmod +x /app/start.sh

CMD ["/app/start.sh"]
