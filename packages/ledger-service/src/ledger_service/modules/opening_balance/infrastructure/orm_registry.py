"""Register cross-service tables on AR/AP metadata so FK resolution works in ledger."""

from __future__ import annotations

from ar_ap_service.modules.ar_ap.infrastructure.models import Base as ArApBase
from coa_service.modules.coa.infrastructure.models import AccountModel
from ledger_service.modules.ledger.infrastructure.models import JournalEntryModel
from tenant_service.modules.tenants.infrastructure.models import TenantModel


def register_opening_balance_orm_metadata() -> None:
    """Mirror referenced tables into AR/AP metadata (separate declarative bases)."""
    if "tenants" in ArApBase.metadata.tables:
        return
    for table in (
        TenantModel.__table__,
        AccountModel.__table__,
        JournalEntryModel.__table__,
    ):
        if table.name not in ArApBase.metadata.tables:
            table.to_metadata(ArApBase.metadata)
