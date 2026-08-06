"""Audit API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AuditLogResponse(BaseModel):
    """Audit log response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    changes: dict[str, object] | None = None
    timestamp: datetime | None = None


class AuditLogListResponse(BaseModel):
    """Paginated audit log list response."""

    items: list[AuditLogResponse]
    count: int
    offset: int
    limit: int


class AuditLogCreate(BaseModel):
    """Audit log creation schema (internal, service-to-service)."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    changes: dict[str, object] | None = Field(default=None)
