"""Audit application services."""
from __future__ import annotations

import uuid


class AuditService:
    """Application service for audit operations."""

    async def create_audit_log(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: str,
        changes: dict | None = None,
    ) -> dict:
        """Create a new audit log entry."""
        raise NotImplementedError

    async def get_audit_logs(
        self,
        tenant_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List audit logs for a tenant."""
        raise NotImplementedError
