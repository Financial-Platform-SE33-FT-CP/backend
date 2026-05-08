"""Audit domain entities."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuditLog:
    """Audit log entry."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: str
    changes: dict | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
