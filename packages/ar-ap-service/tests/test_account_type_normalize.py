"""Account type normalization for raw SQL COA reads."""

from ar_ap_service.modules.ar_ap.infrastructure.repository import _normalize_account_type


def test_normalize_account_type_lowercase_values() -> None:
    assert _normalize_account_type("revenue") == "revenue"
    assert _normalize_account_type("asset") == "asset"


def test_normalize_account_type_legacy_uppercase_names() -> None:
    assert _normalize_account_type("REVENUE") == "revenue"
    assert _normalize_account_type("EXPENSE") == "expense"
