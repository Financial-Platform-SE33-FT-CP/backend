"""FastAPI dependencies for the auth service."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.database import get_session

from auth_service.config import AuthSettings
from auth_service.modules.auth.domain.repository import UserRepository
from auth_service.modules.auth.infrastructure.repository import (
    SqlAlchemyUserRepository,
)
from auth_service.modules.auth.application.services import AuthService


@lru_cache
def get_settings() -> AuthSettings:
    """Return a cached AuthSettings instance."""
    return AuthSettings()


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session from the app state."""
    session_factory = request.app.state.session_factory
    async for session in get_session(session_factory):
        yield session


async def get_user_repository(
    session: AsyncSession,
) -> UserRepository:
    """Return a user repository instance."""
    return SqlAlchemyUserRepository(session)


async def get_auth_service(
    session: AsyncSession,
) -> AuthService:
    """Return an AuthService instance."""
    settings = get_settings()
    user_repo = SqlAlchemyUserRepository(session)
    return AuthService(settings=settings, user_repository=user_repo)
