"""Audit repository interfaces."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date

from audit_service.modules.audit.domain.entities import AuditLog


class AuditLogRepository(ABC):
    """Abstract repository for audit log entries."""

    @abstractmethod
    async def get_by_id(self, tenant_id: uuid.UUID, log_id: uuid.UUID) -> AuditLog | None:
        """Retrieve an audit log by its id, scoped to the tenant."""

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
        action: str | None = None,
        entity_type: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[AuditLog]:
        """List audit logs for a tenant with pagination and optional filters."""

    @abstractmethod
    async def create(self, log: AuditLog) -> AuditLog:
        """Persist a new audit log entry."""
