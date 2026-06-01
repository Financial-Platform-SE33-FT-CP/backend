"""ORM metadata registration for cross-service FK resolution."""

from ar_ap_service.infrastructure.orm_registry import register_ar_ap_orm_metadata
from ar_ap_service.modules.ar_ap.infrastructure.models import Base


def test_register_ar_ap_orm_metadata_includes_referenced_tables() -> None:
    register_ar_ap_orm_metadata()
    assert "tenants" in Base.metadata.tables
    assert "chart_of_accounts" in Base.metadata.tables
    assert "journal_entries" in Base.metadata.tables
