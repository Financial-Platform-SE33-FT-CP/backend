"""Shared test fixtures for shared-lib tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    """Create a fresh FastAPI application for testing."""
    from fastapi import FastAPI

    return FastAPI()


@pytest.fixture
async def engine():
    """Create an in-memory SQLite async engine for testing."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    """Create an async session factory bound to the test engine."""
    from sqlalchemy.ext.asyncio import AsyncSession

    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for testing."""
    async with session_factory() as session:
        yield session


@pytest.fixture
def sample_tenant_id() -> uuid.UUID:
    """Return a sample tenant UUID for testing."""
    return uuid.uuid4()


@pytest.fixture
def sample_user_id() -> uuid.UUID:
    """Return a sample user UUID for testing."""
    return uuid.uuid4()


@pytest.fixture
def sample_account_id() -> uuid.UUID:
    """Return a sample account UUID for testing."""
    return uuid.uuid4()
