"""Audit DTOs."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuditLogDTO:
    """Audit log data transfer object."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    changes: dict | None = None
    timestamp: datetime | None = None
