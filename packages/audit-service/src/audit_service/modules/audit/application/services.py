"""Audit application services."""

from __future__ import annotations

import uuid
from datetime import date

from accounting_shared.exceptions import NotFoundError, ValidationError
from audit_service.modules.audit.application.dto import AuditLogDTO
from audit_service.modules.audit.domain.entities import AuditLog
from audit_service.modules.audit.domain.repository import AuditLogRepository


class AuditService:
    """Application service for audit operations."""

    def __init__(self, repository: AuditLogRepository) -> None:
        self._repository = repository

    async def create_audit_log(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: str,
        changes: dict[str, object] | None = None,
    ) -> AuditLogDTO:
        """Create a new audit log entry."""
        _validate_required(action=action, entity_type=entity_type, entity_id=entity_id)
        log = AuditLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes,
        )
        created = await self._repository.create(log)
        return _to_dto(created)

    async def get_audit_log(
        self,
        tenant_id: uuid.UUID,
        log_id: uuid.UUID,
    ) -> AuditLogDTO:
        """Retrieve a single audit log, scoped to the tenant."""
        log = await self._repository.get_by_id(tenant_id, log_id)
        if log is None:
            raise NotFoundError("Audit log not found.")
        return _to_dto(log)

    async def list_audit_logs(
        self,
        tenant_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        action: str | None = None,
        entity_type: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[AuditLogDTO]:
        """List audit logs for a tenant with pagination and optional filters."""
        logs = await self._repository.list_by_tenant(
            tenant_id,
            limit=limit,
            offset=offset,
            action=action,
            entity_type=entity_type,
            from_date=from_date,
            to_date=to_date,
        )
        return [_to_dto(log) for log in logs]


def _validate_required(*, action: str, entity_type: str, entity_id: str) -> None:
    for name, value in (
        ("action", action),
        ("entity_type", entity_type),
        ("entity_id", entity_id),
    ):
        if not value or not value.strip():
            raise ValidationError(f"{name} is required.")


def _to_dto(log: AuditLog) -> AuditLogDTO:
    return AuditLogDTO(
        id=log.id,
        tenant_id=log.tenant_id,
        user_id=log.user_id,
        action=log.action,
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        changes=log.changes,
        timestamp=log.timestamp,
    )
