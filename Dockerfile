# Multi-service Dockerfile for the backend monorepo.
# Build target is selected via the SERVICE build arg.
#
# Example:
#   docker build --build-arg SERVICE=auth-service -t auth-service .

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY packages/ packages/

ARG SERVICE
RUN uv sync --package ${SERVICE} --no-dev

# Shell-form CMD so bash substitution (${SERVICE//-/_}) is evaluated
CMD uv run --package ${SERVICE} uvicorn ${SERVICE//-/_}.main:app --host 0.0.0.0 --port 8000
