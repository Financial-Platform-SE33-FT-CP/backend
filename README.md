# Accounting Platform — Backend Monorepo

uv workspace monorepo containing all backend microservices and the shared library.

## Packages

| Package | Description |
|---------|-------------|
| `shared-lib` | Shared library: config, database, middleware, exceptions, types |
| `auth-service` | Authentication + RBAC (US-1, US-3) |
| `tenant-service` | Tenant management + COA seeding (US-2) |
| `coa-service` | Chart of Accounts management (US-4) |
| `ledger-service` | Journal entry + trial balance (US-5, US-6) |
| `audit-service` | Audit logging |
| `ar-ap-service` | Accounts Receivable / Payable (US-8-12) |

## Development

```bash
# Install all packages
uv sync

# Run a specific service
uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001

# Run tests for a package
uv run --package auth-service pytest

# Lint
uv run ruff check packages/
```

## Adding a new package

```bash
uv init --package packages/new-service
```
