from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from accounting_shared.types import TenantId, UserId


@dataclass
class Tenant:
    id: TenantId
    name: str
    uen: str | None
    base_currency: str
    gst_registered: bool
    financial_year_start_month: int
    financial_year_start_day: int
    status: str
    created_by_user_id: UserId
    created_at: datetime
    updated_at: datetime


@dataclass
class TenantUser:
    id: str
    tenant_id: TenantId
    user_id: UserId
    role: str
    status: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CoaAccountRow:
    """Read model for COA list (US-2); full CRUD is US-4."""

    id: str
    tenant_id: str
    code: str
    name: str
    account_type: str
    parent_id: str | None
    is_active: bool
    is_system_default: bool
    created_at: datetime
    updated_at: datetime
