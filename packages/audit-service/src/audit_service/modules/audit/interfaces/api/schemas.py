"""Audit API schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    """Audit log response schema."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    changes: dict | None = None
    timestamp: datetime | None = None


class AuditLogCreate(BaseModel):
    """Audit log creation schema."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    changes: dict | None = None
