from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from accounting_shared.types import TenantId, UserId


@dataclass
class Tenant:
    id: TenantId
    name: str
    slug: str
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TenantUser:
    id: str  # UUID string
    tenant_id: TenantId
    user_id: UserId
    role: str  # "admin" | "manager" | "viewer"
    created_at: datetime = field(default_factory=datetime.utcnow)
