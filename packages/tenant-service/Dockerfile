FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency manifests
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN uv sync --no-dev --frozen


FROM python:3.12-slim

WORKDIR /app

# Copy installed environment from builder
COPY --from=builder /app /app

# Copy application code
COPY src/ src/
COPY alembic/ alembic/

EXPOSE 8000

CMD ["uvicorn", "tenant_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
