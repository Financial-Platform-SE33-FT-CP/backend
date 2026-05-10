from __future__ import annotations

import uuid

from accounting_shared.exceptions import ValidationError
from accounting_shared.types import TenantId, UserId
from fastapi import APIRouter, Depends, HTTPException, status

from tenant_service.deps import get_current_user_id, get_tenant_service

from ...application.dto import AddUserRequest, CreateTenantRequest
from ...application.services import TenantService
from ...domain.exceptions import (
    InsufficientPermissionError,
    TenantNotFoundError,
    UserAlreadyMemberError,
)
from .schemas import (
    AddUserRequestSchema,
    CoaAccountResponseSchema,
    CreateTenantRequestSchema,
    TenantListItemResponseSchema,
    TenantSummaryResponseSchema,
    TenantUserResponseSchema,
)

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post(
    "",
    response_model=TenantSummaryResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant(
    body: CreateTenantRequestSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
) -> TenantSummaryResponseSchema:
    try:
        dto = CreateTenantRequest(
            name=body.name,
            uen=body.uen,
            base_currency=body.base_currency,
            gst_registered=body.gst_registered,
            financial_year_start_month=body.financial_year_start_month,
            financial_year_start_day=body.financial_year_start_day,
        )
        result = await service.create_tenant(dto, user_id)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.detail,
        ) from e
    return TenantSummaryResponseSchema(**result.model_dump())


@router.get("", response_model=list[TenantListItemResponseSchema])
async def list_tenants(
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
) -> list[TenantListItemResponseSchema]:
    results = await service.list_tenants(user_id)
    return [TenantListItemResponseSchema(**r.model_dump()) for r in results]


@router.get("/{tenant_id}", response_model=TenantSummaryResponseSchema)
async def get_tenant(
    tenant_id: str,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
) -> TenantSummaryResponseSchema:
    try:
        tid = TenantId(uuid.UUID(tenant_id))
        result = await service.get_tenant(tid, user_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        ) from e
    return TenantSummaryResponseSchema(**result.model_dump())
@router.get("/{tenant_id}/coa", response_model=list[CoaAccountResponseSchema])
async def get_tenant_coa(
    tenant_id: str,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
) -> list[CoaAccountResponseSchema]:
    try:
        tid = TenantId(uuid.UUID(tenant_id))
        results = await service.list_coa(tid, user_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        ) from e
    return [CoaAccountResponseSchema(**r.model_dump()) for r in results]


@router.post(
    "/{tenant_id}/users",
    response_model=TenantUserResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def add_user(
    tenant_id: str,
    body: AddUserRequestSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
) -> TenantUserResponseSchema:
    try:
        tid = TenantId(uuid.UUID(tenant_id))
        dto = AddUserRequest(user_id=body.user_id, role=body.role)
        result = await service.add_user(tid, dto, user_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InsufficientPermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except UserAlreadyMemberError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        ) from e
    return TenantUserResponseSchema(**result.model_dump())
