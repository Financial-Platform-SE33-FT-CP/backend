from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from accounting_shared.database import get_database_url

from .config import TenantSettings
from .modules.tenants.application.services import TenantService
from .modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository

_settings: TenantSettings | None = None
_engine = None
_session_factory = None


def get_settings() -> TenantSettings:
    global _settings
    if _settings is None:
        _settings = TenantSettings()
    return _settings


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session."""
    global _engine, _session_factory

    if _engine is None:
        settings = get_settings()
        url = get_database_url(settings)
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


async def get_tenant_repository(
    session: AsyncSession = Depends(get_async_session),
) -> SqlAlchemyTenantRepository:
    return SqlAlchemyTenantRepository(session)


async def get_tenant_service(
    repository: SqlAlchemyTenantRepository = Depends(get_tenant_repository),
) -> TenantService:
    settings = get_settings()
    return TenantService(repository, settings)
