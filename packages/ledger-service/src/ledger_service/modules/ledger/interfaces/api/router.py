from __future__ import annotations

from datetime import date
from typing import Annotated

from accounting_shared.rbac import P_ACCOUNTING_READ
from accounting_shared.types import TenantId
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_service.deps import (
    RequireLedgerPermission,
    get_async_session,
    require_tenant_id,
)
from ledger_service.modules.ledger.application.services import LedgerService
from ledger_service.modules.ledger.infrastructure.repository import (
    SqlAlchemyJournalEntryRepository,
)
from ledger_service.modules.ledger.interfaces.api.schemas import (
    AccountLedgerViewResponse,
    TrialBalanceResponse,
)

router = APIRouter(tags=["ledger"])


async def get_ledger_service(
    session: AsyncSession = Depends(get_async_session),
) -> LedgerService:
    return LedgerService(SqlAlchemyJournalEntryRepository(session))


@router.get("/health-complete")
async def health_complete() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/accounts/{account_id}/transactions", response_model=AccountLedgerViewResponse)
async def get_account_transactions(
    account_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    _: Annotated[None, Depends(RequireLedgerPermission(P_ACCOUNTING_READ))] = None,
    tenant_id: TenantId = Depends(require_tenant_id),
    service: LedgerService = Depends(get_ledger_service),
) -> AccountLedgerViewResponse:
    result = await service.get_account_transactions(
        tenant_id=str(tenant_id),
        account_id=account_id,
        from_date=from_date,
        to_date=to_date,
    )
    return AccountLedgerViewResponse.model_validate(result.model_dump())


@router.get("/trial-balance", response_model=TrialBalanceResponse)
async def get_trial_balance(
    as_of_date: date | None = None,
    _: Annotated[None, Depends(RequireLedgerPermission(P_ACCOUNTING_READ))] = None,
    tenant_id: TenantId = Depends(require_tenant_id),
    service: LedgerService = Depends(get_ledger_service),
) -> TrialBalanceResponse:
    result = await service.get_trial_balance(
        tenant_id=str(tenant_id),
        as_of_date=as_of_date,
    )
    return TrialBalanceResponse.model_validate(result.model_dump())