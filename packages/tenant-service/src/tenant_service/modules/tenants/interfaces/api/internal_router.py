from __future__ import annotations

import uuid

from accounting_shared.types import TenantId, UserId
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tenant_service.deps import (
    get_tenant_repository,
    verify_internal_service_token,
)
from tenant_service.modules.tenants.application.authorization import evaluate_tenant_permission
from tenant_service.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository

router = APIRouter(prefix="/internal", tags=["internal"])


class InternalAuthzCheckRequest(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    permission: str = Field(..., min_length=1, max_length=128)


class InternalAuthzCheckResponse(BaseModel):
    allowed: bool
    role: str | None = None
    reason: str | None = None


@router.post("/authorization/check", response_model=InternalAuthzCheckResponse)
async def internal_check_permission(
    body: InternalAuthzCheckRequest,
    _: None = Depends(verify_internal_service_token),
    repository: SqlAlchemyTenantRepository = Depends(get_tenant_repository),
) -> InternalAuthzCheckResponse:
    ev = await evaluate_tenant_permission(
        repository,
        tenant_id=TenantId(body.tenant_id),
        user_id=UserId(body.user_id),
        permission=body.permission,
    )
    if ev.allowed and ev.role is not None:
        return InternalAuthzCheckResponse(allowed=True, role=ev.role.value, reason=None)
    if ev.reason == "tenant_not_found":
        return InternalAuthzCheckResponse(allowed=False, role=None, reason="tenant_not_found")
    if ev.reason == "not_member":
        return InternalAuthzCheckResponse(allowed=False, role=None, reason="not_member")
    if ev.role is not None:
        return InternalAuthzCheckResponse(
            allowed=False, role=ev.role.value, reason="permission_denied"
        )
    return InternalAuthzCheckResponse(allowed=False, role=None, reason="permission_denied")
