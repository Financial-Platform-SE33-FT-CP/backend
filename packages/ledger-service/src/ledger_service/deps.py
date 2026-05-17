from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.exceptions import UnauthorizedError
from accounting_shared.middleware.tenant_context import get_current_tenant_id
from ledger_service.config import LedgerSettings
from ledger_service.modules.ledger.application.services import LedgerService
from ledger_service.modules.ledger.infrastructure.repository import (
    SqlAlchemyAccountingPeriodRepository,
    SqlAlchemyJournalEntryRepository,
)


@lru_cache
def get_settings() -> LedgerSettings:
    return LedgerSettings()


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_current_tenant_id_str() -> str:
    tid = get_current_tenant_id()
    if tid is None:
        raise UnauthorizedError("X-Tenant-ID header is required.")
    return str(tid)


async def get_ledger_service(
    session: AsyncSession = Depends(get_async_session),
) -> LedgerService:
    journal_repo = SqlAlchemyJournalEntryRepository(session)
    period_repo = SqlAlchemyAccountingPeriodRepository(session)
    return LedgerService(journal_repo, period_repo)
