from __future__ import annotations

from decimal import Decimal

import pytest
from accounting_shared.exceptions import ValidationError

from ledger_service.modules.opening_balance.application.csv_parser import (
    opening_balance_csv_template,
    parse_opening_balance_csv,
)


def test_template_has_header_and_sections() -> None:
    content = opening_balance_csv_template()
    assert "section,account_code" in content
    assert "trial_balance" in content
    assert "ar_aging" in content
    assert "ap_aging" in content


def test_parse_balanced_minimal_trial_balance() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1000,100.00,0,,,,,\n"
        "trial_balance,3200,0,100.00,,,,,\n"
    )
    parsed = parse_opening_balance_csv(csv_text)
    assert len(parsed.trial_balance) == 2
    assert parsed.trial_balance[0].debit == Decimal("100.00")
    assert parsed.ar_aging == []


def test_parse_includes_ar_and_ap_sections() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1100,50.00,0,,,,,\n"
        "trial_balance,3200,0,50.00,,,,,\n"
        "ar_aging,,,,Acme,50.00,2026-01-15,OPEN-AR-1,\n"
        "ap_aging,,,,Vendor,30.00,2026-02-01,OPEN-AP-1,\n"
    )
    parsed = parse_opening_balance_csv(csv_text)
    assert len(parsed.ar_aging) == 1
    assert parsed.ar_aging[0].customer_name == "Acme"
    assert len(parsed.ap_aging) == 1


def test_parse_rejects_unbalanced_row_with_both_sides() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1000,10.00,10.00,,,,,\n"
        "trial_balance,3200,0,10.00,,,,,\n"
    )
    with pytest.raises(ValidationError, match="only one of debit or credit"):
        parse_opening_balance_csv(csv_text)


def test_parse_rejects_empty_file() -> None:
    with pytest.raises(ValidationError, match="empty"):
        parse_opening_balance_csv("")


def test_parse_rejects_missing_trial_balance() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "ar_aging,,,,Acme,10.00,2026-01-15,REF1,\n"
    )
    with pytest.raises(ValidationError, match="at least one trial_balance"):
        parse_opening_balance_csv(csv_text)


def test_parse_rejects_unknown_section() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "foo,1000,10,0,,,,,\n"
        "trial_balance,3200,0,10,,,,,\n"
    )
    with pytest.raises(ValidationError, match="unknown section"):
        parse_opening_balance_csv(csv_text)
