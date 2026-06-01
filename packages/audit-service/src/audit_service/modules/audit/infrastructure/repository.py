"""Audit repository implementation."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from audit_service.modules.audit.domain.entities import AuditLog
from audit_service.modules.audit.domain.repository import AuditLogRepository
from audit_service.modules.audit.infrastructure.models import AuditLogModel


class SqlAlchemyAuditLogRepository(AuditLogRepository):
    """SQLAlchemy implementation of AuditLogRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, log_id: uuid.UUID) -> AuditLog | None:
        raise NotImplementedError

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        raise NotImplementedError

    async def create(self, log: AuditLog) -> AuditLog:
        raise NotImplementedError
