"""Register cross-service tables on AR/AP metadata so ORM flush can resolve FKs."""

from __future__ import annotations

from sqlalchemy import Column, String, Table

from ar_ap_service.modules.ar_ap.infrastructure.models import Base as ArApBase
from coa_service.modules.coa.infrastructure.models import AccountModel
from tenant_service.modules.tenants.infrastructure.models import TenantModel


def _register_journal_entries_stub() -> None:
    """Stub ``journal_entries`` for FK resolution without depending on ledger-service."""
    if "journal_entries" in ArApBase.metadata.tables:
        return
    Table(
        "journal_entries",
        ArApBase.metadata,
        Column("id", String(36), primary_key=True),
    )


def register_ar_ap_orm_metadata() -> None:
    """Mirror referenced tables into AR/AP metadata (separate declarative bases)."""
    if "tenants" in ArApBase.metadata.tables:
        return
    for table in (TenantModel.__table__, AccountModel.__table__):
        if table.name not in ArApBase.metadata.tables:  # type: ignore[union-attr]
            table.to_metadata(ArApBase.metadata)  # type: ignore[union-attr]
    _register_journal_entries_stub()
