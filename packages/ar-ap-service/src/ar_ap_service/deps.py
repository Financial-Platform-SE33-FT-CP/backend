"""Dependency injection for AR/AP Service."""

from functools import lru_cache
from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ar_ap_service.config import ArApSettings


@lru_cache
def get_settings() -> ArApSettings:
    """Get cached AR/AP settings."""
    return ArApSettings()


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session
