"""Web portal-facing tenant routes (`/tenants/*`) aligned with Next.js `tenant-api.ts`."""

from __future__ import annotations

import re
import uuid

from accounting_shared.exceptions import BadRequestError, ValidationError
from accounting_shared.rbac import (
    P_TENANT_MEMBER_ADD,
    P_TENANT_MEMBER_LIST,
    P_TENANT_MEMBER_REMOVE,
    normalize_role,
    tenant_role_to_frontend_api,
)
from accounting_shared.types import TenantId, UserId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from tenant_service.deps import (
    RequireTenantPermissions,
    get_current_user_id,
    get_tenant_service,
)
from tenant_service.modules.tenants.application.dto import (
    CreateTenantRequest,
    InviteMemberRequest,
    TenantListItemResponse,
    TenantSummaryResponse,
)
from tenant_service.modules.tenants.application.services import TenantService
from tenant_service.modules.tenants.domain.exceptions import UserAlreadyMemberError

router = APIRouter(prefix="/tenants", tags=["tenants-portal"])


def _slug_fallback(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s[:60] if s else "company"


class PortalTenantResponseSchema(BaseModel):
    """DTO returned to the SPA — matches ``TenantDto`` in tenant-api."""

    id: str
    name: str
    slug: str
    base_currency: str
    fiscal_year_start_mmdd: str
    is_active: bool
    created_at: object
    updated_at: object
    current_user_role: str | None


class PortalCreateTenantRequestSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    base_currency: str = Field(..., min_length=3, max_length=3)
    fiscal_year_start_mmdd: str = Field(
        ...,
        min_length=5,
        max_length=5,
        pattern=r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$",
        description="Financial year start as MM-DD (e.g. 04-01).",
    )


class PortalInviteMemberSchema(BaseModel):
    email: EmailStr
    role: str = Field(..., min_length=1, max_length=32)


class PortalMemberResponseSchema(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    email: str
    role: str
    created_at: object


def _list_item_to_portal(row: TenantListItemResponse) -> PortalTenantResponseSchema:
    mmdd = f"{row.financial_year_start_month:02d}-{row.financial_year_start_day:02d}"
    slug = (row.uen or "").strip() or _slug_fallback(row.name)
    pub_role = tenant_role_to_frontend_api(normalize_role(row.role))
    return PortalTenantResponseSchema(
        id=row.id,
        name=row.name,
        slug=slug,
        base_currency=row.base_currency,
        fiscal_year_start_mmdd=mmdd,
        is_active=row.status == "active",
        created_at=row.created_at,
        updated_at=row.created_at,
        current_user_role=pub_role,
    )


def _summary_to_portal(summary: TenantSummaryResponse) -> PortalTenantResponseSchema:
    mmdd = f"{summary.financial_year_start_month:02d}-{summary.financial_year_start_day:02d}"
    slug = (summary.uen or "").strip() or _slug_fallback(summary.name)
    pub_role = tenant_role_to_frontend_api(normalize_role(summary.role))
    return PortalTenantResponseSchema(
        id=summary.id,
        name=summary.name,
        slug=slug,
        base_currency=summary.base_currency,
        fiscal_year_start_mmdd=mmdd,
        is_active=summary.status == "active",
        created_at=summary.created_at,
        updated_at=summary.created_at,
        current_user_role=pub_role,
    )


@router.get("/", response_model=list[PortalTenantResponseSchema])
async def portal_list_tenants(
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
) -> list[PortalTenantResponseSchema]:
    rows = await service.list_tenants(user_id)
    return [_list_item_to_portal(r) for r in rows]


@router.post(
    "/",
    response_model=PortalTenantResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def portal_create_tenant(
    body: PortalCreateTenantRequestSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
) -> PortalTenantResponseSchema:
    mm, dd = body.fiscal_year_start_mmdd.split("-", maxsplit=1)
    try:
        dto = CreateTenantRequest(
            name=body.name.strip(),
            uen=body.slug.strip(),
            base_currency=body.base_currency.upper(),
            gst_registered=False,
            financial_year_start_month=int(mm),
            financial_year_start_day=int(dd),
        )
        summary = await service.create_tenant(dto, user_id)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=e.detail,
        ) from e
    return _summary_to_portal(summary)


@router.get(
    "/{tenant_id}/users",
    response_model=list[PortalMemberResponseSchema],
)
async def portal_list_members(
    tenant_id: uuid.UUID,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_MEMBER_LIST)),
) -> list[PortalMemberResponseSchema]:
    tid = TenantId(tenant_id)
    rows = await service.list_members(tid, user_id)
    sid = str(tenant_id)
    return [
        PortalMemberResponseSchema(
            id=str(r.user_id),
            tenant_id=sid,
            user_id=str(r.user_id),
            email=r.email,
            role=tenant_role_to_frontend_api(normalize_role(r.role)),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post(
    "/{tenant_id}/users",
    response_model=PortalMemberResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def portal_invite_member(
    tenant_id: uuid.UUID,
    body: PortalInviteMemberSchema,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_MEMBER_ADD)),
) -> PortalMemberResponseSchema:
    tid = TenantId(tenant_id)
    invite_email = str(body.email).strip().lower()
    dto = InviteMemberRequest(
        role=body.role.strip(),
        user_id=None,
        email=invite_email,
    )
    sid = str(tenant_id)
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
    return PortalMemberResponseSchema(
        id=str(result.id),
        tenant_id=sid,
        user_id=str(result.user_id),
        email=invite_email,
        role=tenant_role_to_frontend_api(normalize_role(result.role)),
        created_at=result.created_at,
    )


@router.delete(
    "/{tenant_id}/users/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def portal_remove_member(
    tenant_id: uuid.UUID,
    member_user_id: uuid.UUID,
    service: TenantService = Depends(get_tenant_service),
    user_id: UserId = Depends(get_current_user_id),
    _: object = Depends(RequireTenantPermissions(P_TENANT_MEMBER_REMOVE)),
) -> None:
    tid = TenantId(tenant_id)
    await service.remove_member(tid, UserId(member_user_id), user_id)
