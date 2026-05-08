from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from accounting_shared.types import TenantId, UserId

from ....deps import get_tenant_service
from ...application.dto import AddUserRequest, CreateTenantRequest
from ...application.services import TenantService
from ...domain.exceptions import (
    InsufficientPermissionError,
    TenantNotFoundError,
    TenantSlugExistsError,
    UserAlreadyMemberError,
)
from .schemas import (
    AddUserRequestSchema,
    CreateTenantRequestSchema,
    TenantResponseSchema,
    TenantUserResponseSchema,
    VerifyTenantResponseSchema,
)

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _get_current_user_id() -> UserId:
    """Placeholder: extract user from auth context.

    Replace with real auth middleware integration.
    """
    return UserId("00000000-0000-0000-0000-000000000000")


@router.post("/", response_model=TenantResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: CreateTenantRequestSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(_get_current_user_id),
) -> TenantResponseSchema:
    try:
        dto = CreateTenantRequest(name=body.name, slug=body.slug)
        result = await service.create_tenant(dto, user_id)
    except TenantSlugExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return TenantResponseSchema(**result.model_dump())


@router.get("/", response_model=list[TenantResponseSchema])
async def list_tenants(
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(_get_current_user_id),
) -> list[TenantResponseSchema]:
    results = await service.list_tenants(user_id)
    return [TenantResponseSchema(**r.model_dump()) for r in results]


@router.get("/{tenant_id}", response_model=TenantResponseSchema)
async def get_tenant(
    tenant_id: str,
    service: TenantService = Depends(get_tenant_service),
) -> TenantResponseSchema:
    try:
        result = await service.get_tenant(TenantId(tenant_id))
    except TenantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return TenantResponseSchema(**result.model_dump())


@router.get("/{tenant_id}/verify", response_model=VerifyTenantResponseSchema)
async def verify_tenant(
    tenant_id: str,
    service: TenantService = Depends(get_tenant_service),
) -> VerifyTenantResponseSchema:
    tenant = await service.get_tenant(TenantId(tenant_id))
    return VerifyTenantResponseSchema(exists=True, is_active=tenant.is_active)


@router.post(
    "/{tenant_id}/users",
    response_model=TenantUserResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def add_user(
    tenant_id: str,
    body: AddUserRequestSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(_get_current_user_id),
) -> TenantUserResponseSchema:
    try:
        dto = AddUserRequest(user_id=body.user_id, role=body.role)
        result = await service.add_user(TenantId(tenant_id), dto, user_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InsufficientPermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except UserAlreadyMemberError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return TenantUserResponseSchema(**result.model_dump())


@router.delete("/{tenant_id}/users/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    tenant_id: str,
    target_user_id: str,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(_get_current_user_id),
) -> None:
    try:
        await service.remove_user(TenantId(tenant_id), UserId(target_user_id), user_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InsufficientPermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
