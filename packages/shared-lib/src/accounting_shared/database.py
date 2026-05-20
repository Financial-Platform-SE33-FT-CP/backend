"""Async database engine and session factory utilities."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from accounting_shared.config import SharedSettings


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base for cross-service ORM models."""

    pass


def create_engine(settings: SharedSettings) -> AsyncEngine:
    """Build an async SQLAlchemy engine from shared settings."""
    return create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_overflow,
        echo=settings.debug,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an async session factory bound to *engine*."""
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an :class:`AsyncSession` with automatic commit/rollback.

    Commits on success, rolls back on exception, and always closes the
    session when the generator is done.
    """
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
