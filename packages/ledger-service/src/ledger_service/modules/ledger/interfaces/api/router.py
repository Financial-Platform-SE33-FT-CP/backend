from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from accounting_shared.exceptions import NotFoundError
from accounting_shared.rbac import P_ACCOUNTING_READ
from accounting_shared.types import TenantId
from ledger_service.deps import (
    RequireLedgerPermission,
    get_current_tenant_id_str,
    get_ledger_service,
    require_tenant_id,
)
from ledger_service.modules.ledger.application.dto import (
    CreateJournalEntryDTO,
    CreateJournalEntryLineDTO,
)
from ledger_service.modules.ledger.application.services import LedgerService
from ledger_service.modules.ledger.interfaces.api.schemas import (
    AccountLedgerViewResponse,
    JournalEntryCreateRequest,
    JournalEntryListResponse,
    JournalEntryResponse,
    TrialBalanceResponse,
)

router = APIRouter(tags=["ledger"])


def _to_create_dto(body: JournalEntryCreateRequest) -> CreateJournalEntryDTO:
    return CreateJournalEntryDTO(
        entry_date=body.entry_date,
        reference=body.reference,
        description=body.description or "",
        lines=[
            CreateJournalEntryLineDTO(
                account_id=line.account_id,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
                description=line.description,
            )
            for line in body.lines
        ],
    )


@router.get("/health-complete")
async def health_complete() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/journal-entries", response_model=JournalEntryResponse, status_code=201)
async def create_journal_entry(
    body: JournalEntryCreateRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant_id_str)],
    service: Annotated[LedgerService, Depends(get_ledger_service)],
) -> JournalEntryResponse:
    dto = _to_create_dto(body)
    result = await service.create_journal_entry(dto, tenant_id)
    return JournalEntryResponse.model_validate(result.model_dump())


@router.get(
    "/journal-entries/{entry_id}",
    response_model=JournalEntryResponse,
)
async def get_journal_entry(
    entry_id: str,
    tenant_id: Annotated[str, Depends(get_current_tenant_id_str)],
    service: Annotated[LedgerService, Depends(get_ledger_service)],
) -> JournalEntryResponse:
    result = await service.get_journal_entry(tenant_id, entry_id)
    if result is None:
        raise NotFoundError(f"Journal entry '{entry_id}' not found.")
    return JournalEntryResponse.model_validate(result.model_dump())


@router.get("/journal-entries", response_model=JournalEntryListResponse)
async def list_journal_entries(
    tenant_id: Annotated[str, Depends(get_current_tenant_id_str)],
    service: Annotated[LedgerService, Depends(get_ledger_service)],
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> JournalEntryListResponse:
    entries = await service.list_journal_entries(tenant_id, offset, limit)
    return JournalEntryListResponse(
        entries=[JournalEntryResponse.model_validate(e.model_dump()) for e in entries],
        count=len(entries),
        offset=offset,
        limit=limit,
    )


@router.get("/accounts/{account_id}/transactions", response_model=AccountLedgerViewResponse)
async def get_account_transactions(
    account_id: str,
    _: Annotated[None, Depends(RequireLedgerPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[LedgerService, Depends(get_ledger_service)],
    from_date: date | None = None,
    to_date: date | None = None,
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
    _: Annotated[None, Depends(RequireLedgerPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[LedgerService, Depends(get_ledger_service)],
    as_of_date: date | None = None,
) -> TrialBalanceResponse:
    result = await service.get_trial_balance(
        tenant_id=str(tenant_id),
        as_of_date=as_of_date,
    )
    return TrialBalanceResponse.model_validate(result.model_dump())
