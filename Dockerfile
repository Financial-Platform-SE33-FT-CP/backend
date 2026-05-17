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

# Install only runtime dependency (libpq for asyncpg)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/pyproject.toml ./
COPY --from=builder /app/packages/ packages/

ENV PATH="/app/.venv/bin:$PATH"

ARG SERVICE
ENV SERVICE=${SERVICE}

# Shell-form CMD so bash substitution (${SERVICE//-/_}) is evaluated
CMD uv run --package ${SERVICE} uvicorn ${SERVICE//-/_}.main:app --host 0.0.0.0 --port 8000
