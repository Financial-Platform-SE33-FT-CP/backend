from fastapi import APIRouter, Depends, Query

from accounting_shared.exceptions import NotFoundError
from ledger_service.deps import get_current_tenant_id_str, get_ledger_service
from ledger_service.modules.ledger.application.dto import (
    CreateJournalEntryDTO,
    CreateJournalEntryLineDTO,
)
from ledger_service.modules.ledger.application.services import LedgerService
from ledger_service.modules.ledger.interfaces.api.schemas import (
    JournalEntryCreateRequest,
    JournalEntryListResponse,
    JournalEntryResponse,
)

router = APIRouter()


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


@router.post("/journal-entries", response_model=JournalEntryResponse, status_code=201)
async def create_journal_entry(
    body: JournalEntryCreateRequest,
    tenant_id: str = Depends(get_current_tenant_id_str),
    service: LedgerService = Depends(get_ledger_service),
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
    tenant_id: str = Depends(get_current_tenant_id_str),
    service: LedgerService = Depends(get_ledger_service),
) -> JournalEntryResponse:
    result = await service.get_journal_entry(tenant_id, entry_id)
    if result is None:
        raise NotFoundError(f"Journal entry '{entry_id}' not found.")
    return JournalEntryResponse.model_validate(result.model_dump())


@router.get("/journal-entries", response_model=JournalEntryListResponse)
async def list_journal_entries(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    tenant_id: str = Depends(get_current_tenant_id_str),
    service: LedgerService = Depends(get_ledger_service),
) -> JournalEntryListResponse:
    entries = await service.list_journal_entries(tenant_id, offset, limit)
    return JournalEntryListResponse(
        entries=[
            JournalEntryResponse.model_validate(e.model_dump()) for e in entries
        ],
        count=len(entries),
        offset=offset,
        limit=limit,
    )
