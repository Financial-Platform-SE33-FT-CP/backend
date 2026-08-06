"""Audit repository implementation."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from audit_service.modules.audit.domain.entities import AuditLog
from audit_service.modules.audit.domain.repository import AuditLogRepository
from audit_service.modules.audit.infrastructure.models import AuditLogModel


class SqlAlchemyAuditLogRepository(AuditLogRepository):
    """SQLAlchemy implementation of AuditLogRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID, log_id: uuid.UUID) -> AuditLog | None:
        stmt = select(AuditLogModel).where(
            AuditLogModel.tenant_id == tenant_id,
            AuditLogModel.id == log_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model is not None else None

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
        stmt = select(AuditLogModel).where(AuditLogModel.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditLogModel.action == action)
        if entity_type:
            stmt = stmt.where(AuditLogModel.entity_type == entity_type)
        if from_date is not None:
            stmt = stmt.where(
                AuditLogModel.timestamp >= datetime.combine(from_date, time.min)
            )
        if to_date is not None:
            # Inclusive of the whole day: timestamps < midnight of the day after.
            stmt = stmt.where(
                AuditLogModel.timestamp < datetime.combine(to_date + timedelta(days=1), time.min)
            )
        stmt = stmt.order_by(
            AuditLogModel.timestamp.desc(),
            AuditLogModel.id.desc(),
        ).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]

    async def create(self, log: AuditLog) -> AuditLog:
        model = AuditLogModel(
            id=log.id,
            tenant_id=log.tenant_id,
            user_id=log.user_id,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            changes=log.changes,
            timestamp=log.timestamp,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_entity(model)


def _to_entity(model: AuditLogModel) -> AuditLog:
    return AuditLog(
        id=model.id,
        tenant_id=model.tenant_id,
        user_id=model.user_id,
        action=model.action,
        entity_type=model.entity_type,
        entity_id=model.entity_id,
        changes=model.changes,
        timestamp=model.timestamp,
    )
