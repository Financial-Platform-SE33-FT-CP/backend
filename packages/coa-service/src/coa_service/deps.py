from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.database import get_async_session as get_shared_async_session
from accounting_shared.middleware.tenant_context import get_current_tenant_id
from accounting_shared.types import TenantId

from coa_service.config import COASettings
from coa_service.modules.coa.application.services import COAService
from coa_service.modules.coa.domain.repository import AccountRepository
from coa_service.modules.coa.infrastructure.repository import SqlAlchemyAccountRepository


@lru_cache
def get_settings() -> COASettings:
    return COASettings()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_shared_async_session():
        yield session


async def get_coa_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AccountRepository:
    return SqlAlchemyAccountRepository(session)


async def get_coa_service(
    repository: AccountRepository = Depends(get_coa_repository),
) -> COAService:
    return COAService(repository)
