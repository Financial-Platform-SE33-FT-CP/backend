from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from accounting_shared.database import get_session

from coa_service.config import COASettings
from coa_service.modules.coa.application.services import COAService
from coa_service.modules.coa.domain.repository import AccountRepository
from coa_service.modules.coa.infrastructure.repository import SqlAlchemyAccountRepository

_settings: COASettings | None = None
_engine = None
_session_factory = None


@lru_cache
def get_settings() -> COASettings:
    return COASettings()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    global _engine, _session_factory

    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=settings.debug)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async for session in get_session(_session_factory):
        yield session


async def get_coa_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AccountRepository:
    return SqlAlchemyAccountRepository(session)


async def get_coa_service(
    repository: AccountRepository = Depends(get_coa_repository),
) -> COAService:
    return COAService(repository)
