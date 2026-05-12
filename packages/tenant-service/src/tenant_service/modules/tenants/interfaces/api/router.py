from __future__ import annotations

import uuid

from accounting_shared.exceptions import BadRequestError, ValidationError
from accounting_shared.rbac import (
    P_COA_READ,
    P_TENANT_MEMBER_ADD,
    P_TENANT_MEMBER_LIST,
    P_TENANT_MEMBER_REMOVE,
    P_TENANT_MEMBER_ROLE_UPDATE,
    P_TENANT_READ,
)
from accounting_shared.types import TenantId, UserId
from fastapi import APIRouter, Depends, HTTPException, status

from tenant_service.deps import (
    RequireTenantPermissions,
    get_current_user_id,
    get_tenant_service,
)

from ...application.dto import (
    CreateTenantRequest,
    InviteMemberRequest,
    UpdateMemberRoleRequest,
)
from ...application.services import TenantService
from ...domain.exceptions import UserAlreadyMemberError
from .schemas import (
    CoaAccountResponseSchema,
    CreateTenantRequestSchema,
    InviteMemberRequestSchema,
    MemberDetailsResponseSchema,
    MeRoleResponseSchema,
    TenantListItemResponseSchema,
    TenantSummaryResponseSchema,
    TenantUserResponseSchema,
    UpdateMemberRoleRequestSchema,
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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


@router.get(
    "/{tenant_id}/me/role",
    response_model=MeRoleResponseSchema,
)
async def get_my_role(
    tenant_id: uuid.UUID,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_READ)),
) -> MeRoleResponseSchema:
    tid = TenantId(tenant_id)
    result = await service.get_my_role(tid, user_id)
    return MeRoleResponseSchema(**result.model_dump())


@router.get(
    "/{tenant_id}/members",
    response_model=list[MemberDetailsResponseSchema],
)
async def list_members(
    tenant_id: uuid.UUID,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_MEMBER_LIST)),
) -> list[MemberDetailsResponseSchema]:
    tid = TenantId(tenant_id)
    rows = await service.list_members(tid, user_id)
    return [MemberDetailsResponseSchema(**r.model_dump()) for r in rows]


@router.post(
    "/{tenant_id}/members",
    response_model=TenantUserResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    tenant_id: uuid.UUID,
    body: InviteMemberRequestSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_MEMBER_ADD)),
) -> TenantUserResponseSchema:
    tid = TenantId(tenant_id)
    dto = InviteMemberRequest(
        role=body.role,
        user_id=body.user_id,
        email=str(body.email) if body.email is not None else None,
    )
    try:
        result = await service.invite_member(tid, dto, user_id)
    except UserAlreadyMemberError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except BadRequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail) from e
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=e.detail
        ) from e
    return TenantUserResponseSchema(**result.model_dump())


@router.patch(
    "/{tenant_id}/members/{member_user_id}/role",
    response_model=MemberDetailsResponseSchema,
)
async def update_member_role(
    tenant_id: uuid.UUID,
    member_user_id: uuid.UUID,
    body: UpdateMemberRoleRequestSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_MEMBER_ROLE_UPDATE)),
) -> MemberDetailsResponseSchema:
    tid = TenantId(tenant_id)
    dto = UpdateMemberRoleRequest(role=body.role)
    try:
        result = await service.update_member_role(tid, UserId(member_user_id), dto, user_id)
    except BadRequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.detail) from e
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=e.detail
        ) from e
    return MemberDetailsResponseSchema(**result.model_dump())


@router.delete(
    "/{tenant_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    tenant_id: uuid.UUID,
    member_user_id: uuid.UUID,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_MEMBER_REMOVE)),
) -> None:
    tid = TenantId(tenant_id)
    await service.remove_member(tid, UserId(member_user_id), user_id)


@router.get("/{tenant_id}", response_model=TenantSummaryResponseSchema)
async def get_tenant(
    tenant_id: uuid.UUID,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_READ)),
) -> TenantSummaryResponseSchema:
    tid = TenantId(tenant_id)
    result = await service.get_tenant(tid, user_id)
    return TenantSummaryResponseSchema(**result.model_dump())


@router.get("/{tenant_id}/coa", response_model=list[CoaAccountResponseSchema])
async def get_tenant_coa(
    tenant_id: uuid.UUID,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_COA_READ)),
) -> list[CoaAccountResponseSchema]:
    tid = TenantId(tenant_id)
    results = await service.list_coa(tid, user_id)
    return [CoaAccountResponseSchema(**r.model_dump()) for r in results]
