from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from accounting_shared.types import UserId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import TenantSettings
from .modules.tenants.application.services import TenantService
from .modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository

_settings: TenantSettings | None = None
_engine = None
_session_factory = None

security_scheme = HTTPBearer(auto_error=False)


def get_settings() -> TenantSettings:
    global _settings
    if _settings is None:
        _settings = TenantSettings()
    return _settings


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session with commit/rollback on exit."""
    global _engine, _session_factory

    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        _engine = create_async_engine(url, echo=settings.debug)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_access_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    settings: TenantSettings = Depends(get_settings),
) -> dict[str, object]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        return jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail="Not authenticated.") from e


async def get_current_user_id(
    payload: dict[str, object] = Depends(get_access_token_payload),
) -> UserId:
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not authenticated.")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        return UserId(uuid.UUID(str(sub)))
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Not authenticated.") from e


async def get_tenant_repository(
    session: AsyncSession = Depends(get_async_session),
) -> SqlAlchemyTenantRepository:
    return SqlAlchemyTenantRepository(session)


async def get_tenant_service(
    repository: SqlAlchemyTenantRepository = Depends(get_tenant_repository),
) -> TenantService:
    settings = get_settings()
    return TenantService(repository, settings)
