# Repository Guidelines

## Project Overview

Accounting Platform backend — a uv workspace monorepo containing 7 Python packages under `packages/`. The platform serves a multi-tenant accounting system with authentication, tenant management, chart of accounts, general ledger, audit logging, and AR/AP modules. Every service is a FastAPI application following Domain-Driven Design (DDD) layering and sharing common infrastructure via `shared-lib`.

## Architecture & Data Flow

```
Incoming Request
  → Nginx (port 80)
    → FastAPI app (uvicorn, port 8000)
      → CORS Middleware
      → RequestID Middleware (X-Request-ID propagation)
      → TenantContext Middleware (X-Tenant-ID → contextvar)
      → Exception Handlers (DomainException → JSON error response)
      → APIRouter → Service Layer → Repository → SQLAlchemy → PostgreSQL
```

### DDD Layering (every service package)

```
src/<pkg>/
├── main.py              # FastAPI app factory + lifespan
├── config.py            # Settings (pydantic-settings, inherits SharedSettings)
├── deps.py              # FastAPI dependency injection chain
└── modules/<context>/
    ├── domain/           # Entities, value objects, repository interfaces (ABC)
    ├── application/      # DTOs, service classes (use-case handlers)
    ├── infrastructure/   # SQLAlchemy models, repository implementations
    └── interfaces/api/   # Pydantic schemas, APIRouter endpoints
```

### Dependency Injection Chain

```
get_settings() [@lru_cache]
  → get_async_session(request) [reads app.state.session_factory]
    → get_X_repository(session=Depends(get_async_session))
      → get_X_service(repo=Depends(get_X_repository))
```

### Database Ownership (shared PostgreSQL, per-service migrations)

| Service | Tables |
|---------|--------|
| auth-service | `users`, `email_verification_tokens`, `refresh_tokens`, `login_attempts` |
| tenant-service | `tenants`, `tenant_users` |
| coa-service | `chart_of_accounts` |
| ledger-service | `journal_entries`, `journal_entry_lines`, `accounts` |
| audit-service | `audit_logs` |
| ar-ap-service | (to be defined) |

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `backend/` | Workspace root: `pyproject.toml`, `Dockerfile`, `.env.example` |
| `packages/shared-lib/src/accounting_shared/` | Config, database, exceptions, logging, middleware, repository base, types |
| `packages/auth-service/src/auth_service/` | Auth + RBAC (register, login, JWT, email verification) |
| `packages/tenant-service/src/tenant_service/` | Tenant CRUD, user membership, COA seeding |
| `packages/coa-service/src/coa_service/` | Hierarchical chart of accounts management |
| `packages/ledger-service/src/ledger_service/` | Journal entries, trial balance (skeleton) |
| `packages/audit-service/src/audit_service/` | Audit log infrastructure (skeleton) |
| `packages/ar-ap-service/src/ar_ap_service/` | AR/AP operations (skeleton) |
| `alembic/` | Per-service Alembic migrations (`env.py`, `versions/`, `alembic.ini`) |
| `tests/` | Per-service tests (`unit/`, `integration/`, `conftest.py`) |

## Development Commands

```bash
# Install all packages
cd backend && uv sync

# Run a service (hot reload)
uv run --package auth-service uvicorn auth_service.main:app --reload --port 8001

# Run a single test file
uv run --package auth-service pytest tests/unit/test_auth.py -v

# Run all tests for a package with coverage
uv run --package auth-service pytest --cov=auth_service

# Lint/format all packages
uv run ruff check packages/
uv run ruff format packages/

# Type check
uv run mypy packages/

# Generate a new Alembic migration
cd packages/auth-service && uv run alembic revision --autogenerate -m "description"

# Run migrations
cd packages/auth-service && uv run alembic upgrade head
```

## Code Conventions & Common Patterns

### Naming

- **Package names**: hyphenated (`auth-service`, `shared-lib`) — used in `pyproject.toml` and `uv run --package`
- **Python module names**: underscored (`auth_service`, `accounting_shared`) — used in imports and `uvicorn` invocations
- **Config classes**: `<Service>Settings(SharedSettings)` in `config.py`
- **Domain entities**: plain `@dataclass`, not ORM models
- **ORM models**: `<Entity>Model` suffix, inherit from `DeclarativeBase`
- **Repositories**: `<Entity>Repository` (abstract ABC in domain, SQLAlchemy impl in infrastructure)
- **Services**: `<Context>Service` in `application/services.py`
- **Routers**: `APIRouter` instance named `router`, mounted with prefix in `main.py`

### Entry Point Pattern (main.py)

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    engine = create_async_engine(settings.database_url, ...)
    session_factory = create_session_factory(engine)
    app.state.session_factory = session_factory
    app.state.engine = engine
    yield
    await engine.dispose()

def create_app() -> FastAPI:
    app = FastAPI(title="...", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, ...)     # outermost
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(TenantContextMiddleware)  # innermost
    register_exception_handlers(app)
    app.include_router(router, prefix="/<context>")
    return app

app = create_app()
```

### Error Handling

All domain errors inherit from `accounting_shared.exceptions.DomainException`. Subclasses map to HTTP status codes automatically via `register_exception_handlers(app)`:

- `NotFoundError` → 404
- `UnauthorizedError` → 401
- `ForbiddenError` → 403
- `ConflictError` → 409
- `ValidationError` → 422
- `ServiceUnavailableError` → 503

Service-specific exceptions inherit from these (e.g., `InvalidCredentialsError(UnauthorizedError)`).

### Async Patterns

- All database operations are async (`asyncpg` + SQLAlchemy async engine)
- Session dependency uses `AsyncGenerator` with commit/rollback in `get_session`
- Repository base is generic `BaseRepository[T]` with abstract async methods
- Unit of work is an async context manager

### Config Hierarchy

```
SharedSettings (shared-lib)
  ├── AuthSettings    (auth-service)
  ├── TenantSettings  (tenant-service)
  ├── COASettings     (coa-service)
  ├── LedgerSettings  (ledger-service)
  ├── AuditSettings   (audit-service)
  └── ArApSettings    (ar-ap-service)
```

All settings use `pydantic-settings` with `Field(alias=...)` for env var mapping and `env_file=".env"`.

### Testing Patterns

- Framework: pytest + pytest-asyncio (`asyncio_mode = "auto"`)
- Fixtures in `tests/conftest.py`: test settings (in-memory SQLite), async engine, async session
- Directory layout: `tests/unit/`, `tests/integration/`
- Coverage target: included via `--cov=<package_name>`

## Important Files

| File | Role |
|------|------|
| `backend/pyproject.toml` | Workspace config: `[tool.uv.workspace] members = ["packages/*"]`, ruff, mypy, pytest settings |
| `backend/Dockerfile` | Multi-service build: `ARG SERVICE`, `uv sync --package ${SERVICE}` |
| `backend/.pre-commit-config.yaml` | ruff (fix + format) + mypy |
| `packages/shared-lib/src/accounting_shared/config.py` | `SharedSettings` — base for all services |
| `packages/shared-lib/src/accounting_shared/exceptions.py` | `DomainException` hierarchy + `register_exception_handlers()` |
| `packages/shared-lib/src/accounting_shared/middleware/tenant_context.py` | `TenantContextMiddleware` + `get_current_tenant_id()` |
| `packages/shared-lib/src/accounting_shared/database.py` | `create_engine()`, `create_session_factory()`, `get_session()` |
| `packages/<svc>/src/<svc>/main.py` | FastAPI entry point per service |
| `packages/<svc>/src/<svc>/deps.py` | Dependency injection per service |
| `packages/<svc>/alembic/env.py` | Alembic async migration environment |

## Runtime/Tooling Preferences

- **Python**: >=3.12
- **Package manager**: uv (workspace mode)
- **Build backend**: hatchling
- **Linter/Formatter**: ruff (line-length 100, py312 target)
- **Type checker**: mypy (`strict = true`)
- **Database**: PostgreSQL 17 (via asyncpg + SQLAlchemy async)
- **Container**: python:3.12-slim, single Dockerfile for all services via `SERVICE` build arg
