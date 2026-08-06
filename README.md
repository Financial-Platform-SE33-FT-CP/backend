# Accounting Platform — Backend Monorepo

uv workspace monorepo containing 8 backend microservices and the shared library.

## Packages

| Package | Description |
|---------|-------------|
| `shared-lib` | Shared library: config, database, middleware, exceptions, types, RBAC, plans |
| `auth-service` | Authentication + RBAC (US-1, US-3) |
| `tenant-service` | Tenant management + COA seeding (US-2) |
| `coa-service` | Chart of Accounts management (US-4) |
| `ledger-service` | Journal entry + trial balance (US-5, US-6) |
| `audit-service` | Audit logging |
| `ar-ap-service` | Accounts Receivable / Payable (US-8-12) |
| `billing-service` | Stripe checkout, webhook, plan enforcement |

## Quick Start

```bash
# Install all dependencies
uv sync

# Start PostgreSQL (requires Docker)
docker compose up -d

# Run migrations
.\scripts\dev-migrate.ps1   # Windows
# Or manually:
uv run --package auth-service alembic upgrade head

# Start a service
uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001
```

## Development

```bash
# Run a specific service
uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001

# Run tests for a package
uv run --package auth-service pytest

# Run tests with coverage
uv run --package auth-service pytest --cov=auth_service

# Lint & format
uv run ruff check packages/
uv run ruff format packages/

# Type check
uv run mypy packages/

# Generate a new Alembic migration
cd packages/auth-service && uv run alembic revision --autogenerate -m "description"
```

## Service Ports

| Service | Port | Health |
|---------|------|--------|
| auth-service | 8001 | `/health` |
| tenant-service | 8002 | `/health` |
| ledger-service | 8003 | `/health` |
| coa-service | 8004 | `/health` |
| audit-service | 8005 | `/health` |
| ar-ap-service | 8006 | `/health` |
| billing-service | — | `/billing/health-complete` |
| PostgreSQL | 5432 | — |

## CI/CD

- **CI**: Per-service workflows run lint + type check + unit tests + integration tests on push/PR to `develop`.
- **CD**: Multi-service Docker build matrix pushes to `ghcr.io/financial-platform-se33-ft-cp/accounting-platform-{service}`.
- **Release**: Tag-triggered (`v*`) GitHub Release with auto-generated changelog.

## Architecture

All services follow Domain-Driven Design (DDD):

```
packages/<service>/
├── pyproject.toml
├── alembic/                  # Database migrations (per-service version_table)
├── src/<package_name>/
│   ├── main.py               # FastAPI entry point
│   ├── config.py             # Settings (pydantic-settings)
│   ├── deps.py               # Dependency injection
│   └── modules/<context>/
│       ├── domain/            # Entities, value objects, repository interfaces
│       ├── application/       # DTOs, services
│       ├── infrastructure/    # ORM models, repository implementations
│       └── interfaces/api/    # Routers, request/response schemas
└── tests/
    ├── conftest.py
    ├── unit/
    └── integration/
```

## Adding a new package

```bash
uv init --package packages/new-service
```

Then add `shared-lib` as a dependency and follow the DDD layering pattern. See existing services for reference.
