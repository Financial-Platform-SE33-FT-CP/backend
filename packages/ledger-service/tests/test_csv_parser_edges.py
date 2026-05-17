from __future__ import annotations

import pytest
from accounting_shared.exceptions import ValidationError

from ledger_service.modules.opening_balance.application.csv_parser import (
    parse_opening_balance_csv,
)


def test_parse_rejects_missing_header_columns() -> None:
    with pytest.raises(ValidationError, match="missing required columns"):
        parse_opening_balance_csv("section,account_code\n")


def test_parse_skips_blank_rows() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        ",,,,,,,,\n"
        "trial_balance,1000,1,0,,,,,\n"
        "trial_balance,3200,0,1,,,,,\n"
    )
    parsed = parse_opening_balance_csv(csv_text)
    assert len(parsed.trial_balance) == 2


def test_parse_accepts_tb_alias_section() -> None:
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "tb,1000,5,0,,,,,\n"
        "tb,3200,0,5,,,,,\n"
    )
    parsed = parse_opening_balance_csv(csv_text)
    assert len(parsed.trial_balance) == 2
