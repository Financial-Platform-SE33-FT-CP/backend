# conftest.py — shared test fixtures for audit-service
#
# Provides two styles (matching ledger-service):
#   HTTP integration: client fixture (real SQLite file, env-configured app)
#   async DB-level:   engine / tables / session fixtures

from __future__ import annotations

import asyncio
import importlib
import logging
import uuid
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from audit_service.modules.audit.infrastructure.models import AuditLogModel

# Silence all logging during tests to avoid structlog version conflicts
logging.disable(logging.CRITICAL)

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
INTERNAL_TOKEN = "test-internal-token"


# ============================================================================
# Async DB-level fixtures (engine / tables / session)
# ============================================================================

DB_TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    return create_async_engine(DB_TEST_DATABASE_URL, echo=False)


@pytest_asyncio.fixture(scope="session")
async def tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(AuditLogModel.__table__.create, checkfirst=True)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(AuditLogModel.__table__.drop, checkfirst=True)


@pytest_asyncio.fixture
async def session(engine, tables) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


# ============================================================================
# HTTP integration fixtures (client)
# ============================================================================


def _configure_env(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", INTERNAL_TOKEN)


async def _create_all(engine: object) -> None:
    from audit_service.modules.audit.infrastructure.models import AuditLogModel

    metadata = AuditLogModel.metadata
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all, checkfirst=True)


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path.joinpath('audit_test.sqlite').as_posix()}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> Iterator[TestClient]:
    _configure_env(monkeypatch, sqlite_url)

    from audit_service import deps

    deps.get_settings.cache_clear()

    import audit_service.main as main_mod

    importlib.reload(main_mod)

    with TestClient(main_mod.app) as tc:
        asyncio.run(_create_all(tc.app.state.engine))
        yield tc

    deps.get_settings.cache_clear()
