FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required by asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install the package
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
