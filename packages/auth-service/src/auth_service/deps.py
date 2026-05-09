"""FastAPI dependencies for the auth service."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from accounting_shared.database import get_session
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.config import AuthSettings
from auth_service.modules.auth.application.services import AuthService
from auth_service.modules.auth.domain.exceptions import InvalidTokenError
from auth_service.modules.auth.domain.repository import UserRepository
from auth_service.modules.auth.infrastructure.email_service import EmailService
from auth_service.modules.auth.infrastructure.repository import SqlAlchemyUserRepository

security_scheme = HTTPBearer(auto_error=False)


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
    session: AsyncSession = Depends(get_async_session),
) -> UserRepository:
    """Return a user repository instance."""
    return SqlAlchemyUserRepository(session)


def get_email_service(
    settings: AuthSettings = Depends(get_settings),
) -> EmailService:
    """Return an email sender configured from settings."""
    return EmailService(settings)


async def get_auth_service(
    session: AsyncSession = Depends(get_async_session),
    email_service: EmailService = Depends(get_email_service),
) -> AuthService:
    """Return an AuthService instance."""
    settings = get_settings()
    return AuthService(
        settings=settings,
        user_repository=SqlAlchemyUserRepository(session),
        email_service=email_service,
    )


async def get_access_token_value(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> str:
    """Extract Bearer access token or raise InvalidTokenError."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidTokenError("Missing or invalid bearer token.")
    return credentials.credentials
