from dataclasses import dataclass
from datetime import datetime

from accounting_shared.types import AccountId, TenantId


@dataclass
class Account:
    id: AccountId
    tenant_id: TenantId
    code: str
    name: str
    account_type: str  # 'asset' | 'liability' | 'equity' | 'revenue' | 'expense'
    parent_id: AccountId | None
    is_active: bool
    is_system: bool
    description: str
    created_at: datetime
    updated_at: datetime
