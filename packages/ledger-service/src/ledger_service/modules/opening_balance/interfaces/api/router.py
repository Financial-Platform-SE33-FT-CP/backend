"""HTTP API for US-7 opening balance import."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.exceptions import ValidationError
from accounting_shared.rbac import P_ACCOUNTING_POST, P_ACCOUNTING_READ
from accounting_shared.types import TenantId, UserId

from ledger_service.deps import (
    RequireLedgerPermission,
    get_async_session,
    get_current_user_id,
    require_tenant_id,
)
from ledger_service.modules.opening_balance.application.csv_parser import (
    opening_balance_csv_template,
)
from ledger_service.modules.opening_balance.application.opening_balance_service import (
    OpeningBalanceService,
)
from ledger_service.modules.opening_balance.interfaces.api.schemas import (
    OpeningImportResponse,
    OpeningValidateResponse,
    OpeningImportPreviewSchema,
    ValidationErrorItem,
)

router = APIRouter(prefix="/opening-balance", tags=["opening-balance"])


async def get_opening_balance_service(
    session: AsyncSession = Depends(get_async_session),
) -> OpeningBalanceService:
    return OpeningBalanceService(session)


@router.get("/template")
async def download_template(
    _: None = Depends(RequireLedgerPermission(P_ACCOUNTING_READ)),
) -> PlainTextResponse:
    """Download CSV import template."""
    return PlainTextResponse(
        content=opening_balance_csv_template(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="opening_balance_template.csv"'
        },
    )


@router.get("/status")
async def opening_balance_status(
    tenant_id: TenantId = Depends(require_tenant_id),
    service: OpeningBalanceService = Depends(get_opening_balance_service),
    _: None = Depends(RequireLedgerPermission(P_ACCOUNTING_READ)),
) -> dict[str, bool]:
    posted = await service.has_opening_balance(str(tenant_id))
    return {"posted": posted}


@router.post("/validate", response_model=OpeningValidateResponse)
async def validate_opening_balance_csv(
    file: UploadFile = File(...),
    tenant_id: TenantId = Depends(require_tenant_id),
    service: OpeningBalanceService = Depends(get_opening_balance_service),
    _: None = Depends(RequireLedgerPermission(P_ACCOUNTING_POST)),
) -> OpeningValidateResponse:
    """Parse and validate CSV without posting."""
    raw = await file.read()
    if not raw:
        raise ValidationError("Uploaded file is empty.")
    try:
        parsed = service.parse_csv(raw)
    except ValidationError as e:
        return OpeningValidateResponse(
            valid=False,
            errors=[ValidationErrorItem(row=None, field="csv", message=str(e))],
        )

    result, _issues = await service.validate_import(str(tenant_id), parsed)
    preview_data = result.get("preview")
    preview = (
        OpeningImportPreviewSchema(**preview_data) if preview_data else None
    )
    return OpeningValidateResponse(
        valid=result["valid"],
        preview=preview,
        errors=[ValidationErrorItem(**e) for e in result["errors"]],
    )


@router.post("/import", response_model=OpeningImportResponse)
async def import_opening_balance_csv(
    file: UploadFile = File(...),
    entry_date: date = Form(...),
    reference: str = Form(default="OPENING"),
    tenant_id: TenantId = Depends(require_tenant_id),
    user_id: UserId = Depends(get_current_user_id),
    service: OpeningBalanceService = Depends(get_opening_balance_service),
    _: None = Depends(RequireLedgerPermission(P_ACCOUNTING_POST)),
) -> OpeningImportResponse:
    """Validate and post opening trial balance + AR/AP aging."""
    raw = await file.read()
    if not raw:
        raise ValidationError("Uploaded file is empty.")
    parsed = service.parse_csv(raw)
    result = await service.import_opening_balance(
        tenant_id=str(tenant_id),
        parsed=parsed,
        entry_date=entry_date,
        created_by=str(user_id),
        reference=reference.strip() or "OPENING",
    )
    return OpeningImportResponse(**result)
