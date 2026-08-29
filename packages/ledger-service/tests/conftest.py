# conftest.py — shared test fixtures for ledger-service
#
# Provides two styles:
#   US-5 (HTTP integration): client, tenant_id, valid_payload
#   US-7 (async DB-level): engine, tables, session

from __future__ import annotations

import asyncio
import importlib
import logging
import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Column, String, Table, Uuid, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coa_service.modules.coa.infrastructure.models import AccountModel
from ledger_service.modules.ledger.infrastructure.models import (
    AccountingPeriodModel,
    JournalEntryLineModel,
    JournalEntryModel,
    MonthlyAccountBalanceModel,
)

# --- shared constants ---

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT_1_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
ACCOUNT_2_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")

# Silence all logging during tests to avoid structlog version conflicts
logging.disable(logging.CRITICAL)


# ============================================================================
# US-7 fixtures: async DB-level tests (engine / tables / session)
# ============================================================================

DB_TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    return create_async_engine(DB_TEST_DATABASE_URL, echo=False)


@pytest_asyncio.fixture(scope="session")
async def tables(engine):
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))

        def create_journal_tables(sync_conn) -> None:
            # Stub tenants + chart_of_accounts in both metadata scopes so that
            # FK constraints on monthly_account_balances resolve correctly.
            for metadata in (AccountModel.metadata, JournalEntryModel.metadata):
                _ = Table(
                    "tenants",
                    metadata,
                    Column("id", Uuid(as_uuid=True), primary_key=True),
                    Column("name", String(255)),
                    extend_existing=True,
                )
                _ = Table(
                    "chart_of_accounts",
                    metadata,
                    Column("id", Uuid(as_uuid=True), primary_key=True),
                    Column("tenant_id", Uuid(as_uuid=True), nullable=False),
                    Column("code", String(20), nullable=False),
                    Column("name", String(255), nullable=False),
                    Column("type", String(50), nullable=False),
                    Column("parent_id", Uuid(as_uuid=True), nullable=True),
                    Column("is_active", Boolean, nullable=False, server_default="1"),
                    extend_existing=True,
                )
            AccountModel.__table__.create(sync_conn, checkfirst=True)
            JournalEntryModel.__table__.create(sync_conn, checkfirst=True)
            JournalEntryLineModel.__table__.create(sync_conn, checkfirst=True)
            MonthlyAccountBalanceModel.__table__.create(sync_conn, checkfirst=True)
            AccountingPeriodModel.__table__.create(sync_conn, checkfirst=True)

        await conn.run_sync(create_journal_tables)
    yield
    async with engine.begin() as conn:

        def drop_journal_tables(sync_conn) -> None:
            AccountingPeriodModel.__table__.drop(sync_conn, checkfirst=True)
            MonthlyAccountBalanceModel.__table__.drop(sync_conn, checkfirst=True)
            JournalEntryLineModel.__table__.drop(sync_conn, checkfirst=True)
            JournalEntryModel.__table__.drop(sync_conn, checkfirst=True)
            AccountModel.__table__.drop(sync_conn, checkfirst=True)

        await conn.run_sync(drop_journal_tables)


@pytest_asyncio.fixture
async def session(engine, tables) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


# ============================================================================
# US-5 fixtures: HTTP integration tests (client / tenant_id / valid_payload)
# ============================================================================


def _configure_env(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")


async def _create_all(engine: object) -> None:
    from sqlalchemy import Column, DateTime, Boolean

    from ledger_service.modules.ledger.infrastructure.models import Base

    metadata = Base.metadata
    _ = Table(
        "tenants",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("name", String(255)),
        extend_existing=True,
    )
    # Stub chart_of_accounts table matching AccountModel columns needed by
    # ledger-side FK references and AccountModel ORM queries.
    # Columns not provided by raw-SQL _seed_ helpers use server_default / nullable
    # so inserts succeed without specifying every column.
    _ = Table(
        "chart_of_accounts",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("tenant_id", Uuid(as_uuid=True), nullable=False),
        Column("code", String(20), nullable=False),
        Column("name", String(255), nullable=False),
        Column("type", String(50), nullable=False),
        Column("parent_id", Uuid(as_uuid=True), nullable=True),
        Column("is_active", Boolean, nullable=False, server_default="1"),
        Column("is_system_default", Boolean, nullable=False, server_default="0"),
        Column("created_at", DateTime, nullable=False, server_default=text("(datetime('now'))")),
        Column("updated_at", DateTime, nullable=False, server_default=text("(datetime('now'))")),
        extend_existing=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all, checkfirst=True)


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path.joinpath('ledger_test.sqlite').as_posix()}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> Iterator[TestClient]:
    _configure_env(monkeypatch, sqlite_url)

    from ledger_service import deps

    deps.get_settings.cache_clear()

    import ledger_service.main as main_mod

    importlib.reload(main_mod)

    with TestClient(main_mod.app) as tc:
        asyncio.run(_create_all(tc.app.state.engine))
        yield tc

    deps.get_settings.cache_clear()


@pytest.fixture
def tenant_id() -> str:
    return str(TENANT_ID)


@pytest.fixture
def valid_payload() -> dict:
    return {
        "entry_date": date.today().isoformat(),
        "reference": "JE-001",
        "description": "Test journal entry",
        "lines": [
            {
                "account_id": str(ACCOUNT_1_ID),
                "debit_amount": "100.00",
                "credit_amount": "0.00",
                "description": "Debit cash",
            },
            {
                "account_id": str(ACCOUNT_2_ID),
                "debit_amount": "0.00",
                "credit_amount": "100.00",
                "description": "Credit revenue",
            },
        ],
    }
