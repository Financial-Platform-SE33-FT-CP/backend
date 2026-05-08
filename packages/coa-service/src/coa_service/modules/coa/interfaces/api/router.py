from fastapi import APIRouter, Depends, HTTPException

from accounting_shared.middleware.tenant_context import get_current_tenant_id
from accounting_shared.types import TenantId

from coa_service.config import COASettings
from coa_service.deps import get_coa_service, get_settings
from coa_service.modules.coa.application.dto import (
    AccountResponse,
    AccountTreeNode,
    CreateAccountRequest,
    UpdateAccountRequest,
)
from coa_service.modules.coa.application.services import COAService
from coa_service.modules.coa.domain.exceptions import (
    AccountCodeExistsError,
    AccountNotFoundError,
    CannotDeleteSystemAccountError,
    InvalidAccountTypeError,
)

router = APIRouter(tags=["chart-of-accounts"])


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    tenant_id: TenantId = Depends(get_current_tenant_id),
    service: COAService = Depends(get_coa_service),
):
    return await service.list_accounts(tenant_id)


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    body: CreateAccountRequest,
    tenant_id: TenantId = Depends(get_current_tenant_id),
    service: COAService = Depends(get_coa_service),
):
    try:
        return await service.create_account(tenant_id, body)
    except AccountCodeExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except InvalidAccountTypeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    body: UpdateAccountRequest,
    tenant_id: TenantId = Depends(get_current_tenant_id),
    service: COAService = Depends(get_coa_service),
):
    try:
        return await service.update_account(account_id, tenant_id, body)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CannotDeleteSystemAccountError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.get("/accounts/tree", response_model=list[AccountTreeNode])
async def get_account_tree(
    tenant_id: TenantId = Depends(get_current_tenant_id),
    service: COAService = Depends(get_coa_service),
):
    return await service.get_account_tree(tenant_id)


@router.post("/accounts/seed", response_model=list[AccountResponse], status_code=201)
async def seed_default_accounts(
    tenant_id: TenantId = Depends(get_current_tenant_id),
    service: COAService = Depends(get_coa_service),
    settings: COASettings = Depends(get_settings),
):
    return await service.seed_default_coa(tenant_id, settings)
