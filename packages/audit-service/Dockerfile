# Audit Service — Dockerfile
FROM python:3.12-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
COPY packages/ packages/

RUN uv sync --package audit-service --frozen --no-dev

CMD ["uv", "run", "--package", "audit-service", "uvicorn", "audit_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
