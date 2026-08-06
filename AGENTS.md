# Repository Guidelines

## Project Overview

Accounting Platform backend — a uv workspace monorepo containing 8 Python packages under `packages/`. The platform serves a multi-tenant accounting system with authentication, tenant management, chart of accounts, general ledger, audit logging, AR/AP, and billing (Stripe) modules. Every service is a FastAPI application following Domain-Driven Design (DDD) layering and sharing common infrastructure via `shared-lib`.

## Architecture & Data Flow

```
Incoming Request
  → Nginx (port 80)
    → FastAPI app (uvicorn, port 8000)
      → CORS Middleware
      → RequestID Middleware (X-Request-ID propagation)
      → AuditContext Middleware (captures audit metadata; NOT on audit-service itself)
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

Two engine/session patterns coexist:
- **Pattern A (app.state)** — auth-service, ledger-service, audit-service, ar-ap-service, billing-service: engine + session_factory created in `lifespan()`, stored on `app.state`.
- **Pattern B (module globals)** — tenant-service, coa-service: engine + session_factory as module-level globals with lazy init in `get_async_session()`.

### Database Ownership (shared PostgreSQL, per-service migrations)

|Service|Tables|
|---|---|
|auth-service|`users`, `email_verification_tokens`, `refresh_tokens`, `login_attempts`|
|tenant-service|`tenants`, `tenant_users`|
|coa-service|`chart_of_accounts`|
|ledger-service|`journal_entries`, `journal_entry_lines`, `accounts`|
|audit-service|`audit_logs`|
|ar-ap-service|`invoices`, `invoice_lines`, `customers`, `payments`, `credit_notes`, `bills`, `vendors`, `bill_payments`, `bank_accounts`, `bank_transactions`, `gst_transactions`|
|billing-service|(none yet — skeleton)|

All services share one PostgreSQL database. Each tracks migrations independently via per-service `version_table` suffix (e.g., `alembic_version_coa_service`).

### Service Port Map

|Service|Port|Health|
|---|---|---|
|auth-service|8001|`/health`|
|tenant-service|8002|`/health`|
|ledger-service|8003|`/health`|
|coa-service|8004|`/health`|
|audit-service|8005|`/health`|
|ar-ap-service|8006|`/health`|
|billing-service|(not in dev-start)|`/billing/health-complete`|
|PostgreSQL|5432|—|
|Frontend (Next.js)|3000|—|

### RBAC Architecture

Two approaches coexist:

1. **Direct DB (tenant-service)**: `RequireTenantPermissions` class loads membership from its own `tenant_users` table, resolves role, checks permissions locally. Writes `RBAC_DENIED` audit entries on failure.
2. **Delegated (all other services)**: `authorize_via_tenant_service()` calls `POST /internal/authorization/check` on tenant-service with internal token. Permission check class pattern: `Require<Service>Permission(permission)`.

## Key Directories

|Directory|Purpose|
|---|---|
|`backend/`|Workspace root: `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.env.example`|
|`packages/shared-lib/src/accounting_shared/`|Config, database, exceptions, logging, middleware, repository base, types, RBAC, plans, audit client, HTTP internal client, unit of work|
|`packages/auth-service/src/auth_service/`|Auth + RBAC (register, login, JWT, email verification)|
|`packages/tenant-service/src/tenant_service/`|Tenant CRUD, user membership, COA seeding, authorization endpoint|
|`packages/coa-service/src/coa_service/`|Hierarchical chart of accounts management|
|`packages/ledger-service/src/ledger_service/`|Journal entries, trial balance, opening balance import|
|`packages/audit-service/src/audit_service/`|Audit log infrastructure|
|`packages/ar-ap-service/src/ar_ap_service/`|AR/AP: invoices, bills, payments, bank reconciliation, GST|
|`packages/billing-service/src/billing_service/`|Stripe checkout, webhook, plan enforcement (skeleton — logic lives in router)|
|`alembic/`|Per-service Alembic migrations (`env.py`, `versions/`, `alembic.ini`)|
|`tests/`|Per-service tests (`unit/`, `integration/`, `conftest.py`)|
|`scripts/`|PowerShell dev scripts (`dev-migrate.ps1`, `dev-start-us8.ps1`)|
|`.github/workflows/`|CI/CD pipelines (9 workflow files)|

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

# Run all migrations (PowerShell)
.\scripts\dev-migrate.ps1

# Start US-8 dev services (PowerShell)
.\scripts\dev-start-us8.ps1
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
    app.add_middleware(AuditContextMiddleware, ...)  # optional
    app.add_middleware(TenantContextMiddleware)  # innermost
    register_exception_handlers(app)
    app.include_router(router, prefix="/<context>")
    return app

app = create_app()
```

**Note**: audit-service and billing-service do NOT use `create_app()` — they create `app` at module top-level. billing-service also omits `setup_logging()` and `AuditContextMiddleware`.

### Error Handling

All domain errors inherit from `accounting_shared.exceptions.DomainException`. Subclasses map to HTTP status codes automatically via `register_exception_handlers(app)`:

- `NotFoundError` → 404
- `UnauthorizedError` → 401
- `ForbiddenError` → 403
- `ConflictError` → 409
- `BadRequestError` → 400
- `ValidationError` → 422
- `ServiceUnavailableError` → 503

Service-specific exceptions inherit from these (e.g., `InvalidCredentialsError(UnauthorizedError)`).

### Async Patterns

- All database operations are async (`asyncpg` + SQLAlchemy async engine)
- Session dependency uses `AsyncGenerator` with commit/rollback in `get_session`
- Repository base is generic `BaseRepository[T]` with abstract async methods
- Unit of work is an async context manager (`accounting_shared.unit_of_work`)

### Config Hierarchy

```
SharedSettings (shared-lib)
  ├── AuthSettings       — bcrypt_rounds, SMTP, email verification, login rate limiting
  ├── TenantSettings     — internal_api_token, audit_service_url, trust_x_user_id_header
  ├── COASettings        — tenant_internal_api_token, default_coa_accounts
  ├── LedgerSettings     — tenant_internal_api_token
  ├── AuditSettings      — internal_api_token, tenant_internal_api_token
  ├── ArApSettings       — AR/AP/GST control account codes
  └── BillingSettings    — stripe_secret_key, stripe_webhook_secret, stripe_mock_mode, stripe_price_ids
```

All settings use `pydantic-settings` with `Field(alias=...)` for env var mapping and `env_file=(".env", _BACKEND_ROOT_ENV)` for dual-location .env discovery.

### Shared-Lib Module Inventory

|Module|Key Exports|
|---|---|
|`config.py`|`SharedSettings` — base settings class|
|`database.py`|`Base` (DeclarativeBase), `create_engine()`, `create_session_factory()`, `get_session()`|
|`exceptions.py`|`DomainException` hierarchy + `register_exception_handlers()`|
|`types.py`|`TenantId`, `UserId`, `AccountId`, `JournalEntryId` (NewType), `PositiveAmount` (Annotated), factory functions|
|`middleware/request_id.py`|`RequestIDMiddleware`|
|`middleware/tenant_context.py`|`TenantContextMiddleware`, `get_current_tenant_id()`, `set_current_tenant_id()`|
|`middleware/audit_context.py`|`AuditContextMiddleware`, `AuditContext`, `get_audit_context()`|
|`rbac.py`|`Permission` enum, `check_permission()`, role→permissions mapping|
|`plans.py`|`PlanTier` enum, `PlanLimits` TypedDict, `PLAN_LIMITS` dict|
|`audit_client.py`|`log_audit_event()` — async HTTP client for audit logging|
|`http_internal.py`|`post_json()` — internal service-to-service HTTP helper|
|`logging.py`|`setup_logging()` — structured logging via structlog|
|`repository.py`|`BaseRepository[T]` — generic async repository ABC|
|`unit_of_work.py`|`UnitOfWork` — async context manager base|
|`infrastructure/`|Tenant membership read model + membership reader|

### Testing Patterns

- **Framework**: pytest + pytest-asyncio (`asyncio_mode = "auto"`)
- **Database in tests**: SQLite via `aiosqlite` (in-memory or tmp_path file); `testcontainers[postgres]` is installed but unused in actual test code
- **Fixtures** in `tests/conftest.py`: test settings (monkeypatch env vars), async engine, async session

Four test patterns coexist:

|Pattern|Used By|Description|
|---|---|---|
|**TestClient + SQLite file**|auth-service, ledger-service, audit-service|`TestClient(app)` with real app + aiosqlite tmp_path SQLite. `importlib.reload` for app reconstitution per fixture variant. `dependency_overrides` for auth mocks.|
|**DB-level engine + :memory:**|ledger-service, audit-service, coa-service, shared-lib|Session-scoped async engine with `sqlite+aiosqlite:///:memory:`. Tables created via `conn.run_sync(Base.metadata.create_all)`. Function-scoped sessions with rollback.|
|**In-memory fakes**|ar-ap-service|Fake repository classes store entities in dicts. No database at all. `FakeLedgerPoster`, `FakeInvoiceRepository`, etc.|
|**httpx AsyncClient**|tenant-service|`httpx.AsyncClient(transport=ASGITransport(app=app))` instead of TestClient. Mock repos with `MagicMock(spec=...)`.|

**Test organization**: `tests/unit/` (service-level unit tests), `tests/integration/` (API integration tests), some services have tests at root `tests/`. Naming: `test_<module>.py`, classes `Test<Feature>`, methods `test_<scenario>`.

## CI/CD

### Workflow Inventory (`.github/workflows/`)

|Workflow|Trigger|Purpose|
|---|---|---|
|`ci-shared-lib.yml`|push/PR on shared-lib/**|Lint, type check, unit tests (no integration)|
|`ci-{service}.yml` (6 files)|push/PR on service/**|Lint+type → unit tests → integration tests (Testcontainers)|
|`docker-build-backend.yml`|push/PR on backend/**|Matrix build × 7 services → GHCR. PRs build-only, pushes deploy.|
|`release.yml`|tag `v*`|Changelog + GitHub Release with Docker image URLs|

**Missing**: billing-service has no CI workflow (no `ci-billing-service.yml`).

### Service CI Template

```
lint-and-type:
  ruff check (E,W,F only) → ruff format check → mypy
unit-tests (needs: lint-and-type):
  pytest with coverage XML → upload artifact (7-day retention)
integration-tests (needs: lint-and-type):
  pytest with Testcontainers (Ryuk disabled, socket override)
  gracefully handles missing tests/integration/ directory
```

All CI jobs use: `uv sync --package {service} --group dev` → `uv run --package {service} {tool}`.

### Docker (multi-stage, single Dockerfile)

- **Builder stage**: `python:3.12-slim` + `gcc`, runs `uv sync --package ${SERVICE} --no-dev`
- **Runtime stage**: `python:3.12-slim` + `libpq5` + `curl`, copies `.venv`
- **Startup**: POSIX-compatible `tr` substitution (`${SERVICE//-/_}` → `tr - _`), generates `/app/start.sh`: `uvicorn {mod}.main:app --host 0.0.0.0 --port 8000`
- **Registry**: `ghcr.io/financial-platform-se33-ft-cp/accounting-platform-{service}`
- **Tags**: branch, semver (`vX.Y.Z` + `X.Y`), short SHA

### Pre-commit

- `ruff` v0.8.0 (fix + format)
- `mypy` v1.13.0 (with pydantic, sqlalchemy, structlog stubs as additional_dependencies)

### Alembic Migration Pattern

- Each service has its own `alembic/` directory
- Per-service `version_table` in `env.py`: `alembic_version_{service_name}` (e.g., `alembic_version_coa_service`)
- All models import into `Base.metadata` from `accounting_shared.database`
- `scripts/dev-migrate.ps1` runs all 6 services' migrations in sequence (auth→tenant→coa→ledger→ar-ap→audit)

## Anomalies & Service-Specific Differences

|Anomaly|Services|Detail|
|---|---|---|
|No `create_app()` factory|audit-service, billing-service|`app` created at module top-level|
|No `setup_logging()`|billing-service|No structured logging initialization|
|No `AuditContextMiddleware`|audit-service, billing-service|audit-service IS the audit system; billing-service simply omits it|
|Global engine/session in deps.py|tenant-service, coa-service|Module-level globals with lazy init instead of app.state|
|`@lru_cache` missing on get_settings|tenant-service|Global `_settings` variable with manual caching|
|Hardcoded CORS `["*"]`|audit-service, billing-service|Other services read from `settings.cors_origins`|
|Multiple API routers|tenant-service|`router.py` (public), `portal_router.py` (portal), `internal_router.py` (service-to-service)|
|Extra module: `opening_balance`|ledger-service|Second bounded context with own DDD layers; CSV import, trial balance, AR/AP aging|
|Service-level `infrastructure/orm_registry.py`|ar-ap-service|Cross-service ORM metadata mirroring (tenants, accounts, journal_entries)|
|DDD layers empty (stubs only)|billing-service|domain/, application/, infrastructure/ contain only `__init__.py`; all logic in `interfaces/api/router.py`|
|Direct cross-service import|billing-service|Imports `TenantModel` from `tenant_service.modules.tenants.infrastructure.models`|
|`security/` at service root|auth-service|`token_hash.py` utility placed outside modules/auth/|

## Important Files

|File|Role|
|---|---|
|`backend/pyproject.toml`|Workspace config: `[tool.uv.workspace] members = ["packages/*"]`, ruff, mypy, pytest settings|
|`backend/Dockerfile`|Multi-service build: `ARG SERVICE`, `uv sync --package ${SERVICE}`|
|`backend/docker-compose.yml`|Local PostgreSQL 17 container (port 5432, volume `accounting_pg_data`)|
|`backend/.pre-commit-config.yaml`|ruff (fix + format) + mypy|
|`backend/.env.example`|All env vars: Database, JWT, CORS, Service URLs, Internal tokens, Stripe, SMTP, AR/AP control accounts|
|`packages/shared-lib/src/accounting_shared/config.py`|`SharedSettings` — base for all services|
|`packages/shared-lib/src/accounting_shared/exceptions.py`|`DomainException` hierarchy + `register_exception_handlers()`|
|`packages/shared-lib/src/accounting_shared/database.py`|`create_engine()`, `create_session_factory()`, `get_session()`|
|`packages/shared-lib/src/accounting_shared/middleware/tenant_context.py`|`TenantContextMiddleware` + `get_current_tenant_id()`|
|`packages/shared-lib/src/accounting_shared/middleware/audit_context.py`|`AuditContextMiddleware` + `get_audit_context()`|
|`packages/shared-lib/src/accounting_shared/rbac.py`|Permission enum + role→permissions mapping|
|`packages/shared-lib/src/accounting_shared/plans.py`|Subscription plan tiers + limits|
|`packages/shared-lib/src/accounting_shared/types.py`|Domain type aliases (`TenantId`, `UserId`, etc.) + factory functions|
|`packages/<svc>/src/<svc>/main.py`|FastAPI entry point per service|
|`packages/<svc>/src/<svc>/config.py`|Service-specific settings|
|`packages/<svc>/src/<svc>/deps.py`|Dependency injection per service|
|`packages/<svc>/alembic/env.py`|Alembic async migration environment (per-service version_table)|
|`packages/<svc>/tests/conftest.py`|Test fixtures per service|

## Runtime/Tooling Preferences

- **Python**: >=3.12
- **Package manager**: uv (workspace mode)
- **Build backend**: hatchling
- **Linter/Formatter**: ruff (line-length 100, py312 target, rules: E, F, I, N, W, UP, B, C4, SIM)
- **Type checker**: mypy (`strict = true`)
- **Database**: PostgreSQL 17 (via asyncpg + SQLAlchemy async)
- **Test DB**: SQLite via aiosqlite (in-memory or tmp_path)
- **Container**: `python:3.12-slim`, single multi-stage Dockerfile for all services via `SERVICE` build arg
- **Registry**: `ghcr.io/financial-platform-se33-ft-cp/accounting-platform-{service}`
