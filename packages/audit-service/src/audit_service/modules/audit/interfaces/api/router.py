"""Audit API routes."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from accounting_shared.rbac import P_ACCOUNTING_READ
from accounting_shared.types import TenantId
from audit_service.deps import (
    RequireAuditPermission,
    get_audit_service,
    require_tenant_id,
    verify_internal_service_token,
)
from audit_service.modules.audit.application.services import AuditService
from audit_service.modules.audit.interfaces.api.schemas import (
    AuditLogCreate,
    AuditLogListResponse,
    AuditLogResponse,
)

router = APIRouter(tags=["audit"])


@router.get("/health-complete")
async def health_complete() -> dict[str, str]:
    """Complete health check for the audit module."""
    return {"status": "ok"}


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    _: Annotated[None, Depends(RequireAuditPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[AuditService, Depends(get_audit_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    action: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> AuditLogListResponse:
    """List audit logs for the tenant, newest first, with optional filters."""
    logs = await service.list_audit_logs(
        tenant_id,
        limit=limit,
        offset=offset,
        action=action,
        entity_type=entity_type,
        from_date=from_date,
        to_date=to_date,
    )
    items = [AuditLogResponse.model_validate(log.__dict__) for log in logs]
    return AuditLogListResponse(
        items=items,
        count=len(items),
        offset=offset,
        limit=limit,
    )


@router.get("/audit-logs/{log_id}", response_model=AuditLogResponse)
async def get_audit_log(
    _: Annotated[None, Depends(RequireAuditPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[AuditService, Depends(get_audit_service)],
    log_id: uuid.UUID,
) -> AuditLogResponse:
    """Retrieve a single audit log entry."""
    result = await service.get_audit_log(tenant_id, log_id)
    return AuditLogResponse.model_validate(result.__dict__)


@router.post("/audit-logs", response_model=AuditLogResponse, status_code=201)
async def create_audit_log(
    _: Annotated[None, Depends(verify_internal_service_token)],
    service: Annotated[AuditService, Depends(get_audit_service)],
    body: AuditLogCreate,
) -> AuditLogResponse:
    """Create an audit log entry (service-to-service; X-Internal-Token required)."""
    result = await service.create_audit_log(
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        action=body.action,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        changes=body.changes,
    )
    return AuditLogResponse.model_validate(result.__dict__)
