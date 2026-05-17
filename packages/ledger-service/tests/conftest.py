from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ledger_service.modules.ledger.infrastructure.models import (
    JournalEntryLineModel,
    JournalEntryModel,
)

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    return create_async_engine(TEST_DATABASE_URL, echo=False)


@pytest_asyncio.fixture(scope="session")
async def tables(engine):
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))

        def create_journal_tables(sync_conn) -> None:
            JournalEntryModel.__table__.create(sync_conn, checkfirst=True)
            JournalEntryLineModel.__table__.create(sync_conn, checkfirst=True)

        await conn.run_sync(create_journal_tables)
    yield
    async with engine.begin() as conn:
        def drop_journal_tables(sync_conn) -> None:
            JournalEntryLineModel.__table__.drop(sync_conn, checkfirst=True)
            JournalEntryModel.__table__.drop(sync_conn, checkfirst=True)

        await conn.run_sync(drop_journal_tables)


@pytest_asyncio.fixture
async def session(engine, tables) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
