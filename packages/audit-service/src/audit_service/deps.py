"""Dependency injection helpers."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from audit_service.config import AuditSettings


@lru_cache
def get_settings() -> AuditSettings:
    """Return cached AuditSettings singleton."""
    return AuditSettings()  # type: ignore[call-arg]


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession from the app state session factory."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session
