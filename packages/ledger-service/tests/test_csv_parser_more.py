from __future__ import annotations

import pytest
from accounting_shared.exceptions import ValidationError

from ledger_service.modules.opening_balance.application.csv_parser import (
    opening_balance_csv_template,
    parse_opening_balance_csv,
)


def test_parse_rejects_invalid_decimal() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1000,abc,0,,,,,\n"
        "trial_balance,3200,0,1,,,,,\n"
    )
    with pytest.raises(ValidationError, match="invalid debit"):
        parse_opening_balance_csv(csv_text)


def test_parse_rejects_negative_amount() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1000,-1,0,,,,,\n"
        "trial_balance,3200,0,1,,,,,\n"
    )
    with pytest.raises(ValidationError, match="cannot be negative"):
        parse_opening_balance_csv(csv_text)


def test_parse_rejects_missing_account_code_on_tb() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,,1,0,,,,,\n"
        "trial_balance,3200,0,1,,,,,\n"
    )
    with pytest.raises(ValidationError, match="account_code is required"):
        parse_opening_balance_csv(csv_text)


def test_parse_accepts_excel_style_due_date() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1100,1200,0,,,,,\n"
        "trial_balance,3200,0,1200,,,,,\n"
        "ar_aging,,,,Acme,500.00,2026/1/15,OPEN-AR-001,\n"
        "ar_aging,,,,Beta,700.00,2026/2/1,OPEN-AR-002,\n"
    )
    parsed = parse_opening_balance_csv(csv_text)
    assert parsed.ar_aging[0].due_date.isoformat() == "2026-01-15"
    assert parsed.ar_aging[1].due_date.isoformat() == "2026-02-01"


def test_downloaded_template_still_parses_after_excel_dates() -> None:
    """Simulate Excel rewriting ISO dates to 2026/1/15 style."""
    base = opening_balance_csv_template()
    excel_like = base.replace("2026-01-15", "2026/1/15").replace("2026-02-01", "2026/2/1")
    excel_like = excel_like.replace("2026-01-20", "2026/1/20").replace("2026-02-10", "2026/2/10")
    parsed = parse_opening_balance_csv(excel_like)
    assert len(parsed.ar_aging) == 2
    assert len(parsed.ap_aging) == 2


def test_parse_rejects_bad_ar_due_date() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1100,1,0,,,,,\n"
        "trial_balance,3200,0,1,,,,,\n"
        "ar_aging,,,,Acme,1,not-a-date,REF,\n"
    )
    with pytest.raises(ValidationError, match="due_date"):
        parse_opening_balance_csv(csv_text)


def test_parse_bytes_input() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1000,1,0,,,,,\n"
        "trial_balance,3200,0,1,,,,,\n"
    ).encode("utf-8-sig")
    parsed = parse_opening_balance_csv(csv_text)
    assert len(parsed.trial_balance) == 2
