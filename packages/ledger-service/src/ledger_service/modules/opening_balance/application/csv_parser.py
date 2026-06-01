"""CSV parser for US-7 opening balance import."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from accounting_shared.exceptions import ValidationError

from ledger_service.modules.opening_balance.domain.entities import (
    ApAgingLine,
    ArAgingLine,
    ParsedOpeningImport,
    TrialBalanceLine,
)

REQUIRED_HEADERS = (
    "section",
    "account_code",
    "debit",
    "credit",
    "counterparty_name",
    "amount",
    "due_date",
    "reference",
    "description",
)

_SECTION_ALIASES = {
    "trial_balance": "trial_balance",
    "tb": "trial_balance",
    "trial balance": "trial_balance",
    "ar_aging": "ar_aging",
    "ar": "ar_aging",
    "ar aging": "ar_aging",
    "ap_aging": "ap_aging",
    "ap": "ap_aging",
    "ap aging": "ap_aging",
}


def opening_balance_csv_template() -> str:
    """Return downloadable CSV template content."""
    return (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1000,5000.00,0,,,,,Cash and bank opening\n"
        "trial_balance,1100,1200.00,0,,,,,Accounts receivable control\n"
        "trial_balance,2000,0,800.00,,,,,Accounts payable control\n"
        "trial_balance,3200,0,5400.00,,,,,Opening balance equity\n"
        "ar_aging,,,,Acme Pte Ltd,500.00,2026-01-15,OPEN-AR-001,Opening customer balance\n"
        "ar_aging,,,,Beta Corp,700.00,2026-02-01,OPEN-AR-002,Opening customer balance\n"
        "ap_aging,,,,Supplier Co,300.00,2026-01-20,OPEN-AP-001,Opening vendor balance\n"
        "ap_aging,,,,Utilities Ltd,500.00,2026-02-10,OPEN-AP-002,Opening vendor balance\n"
    )


def _normalize_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _parse_decimal(raw: str, *, row: int, field: str) -> Decimal:
    text = (raw or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        value = Decimal(text)
    except InvalidOperation as e:
        msg = f"Row {row}: invalid {field} '{raw}'."
        raise ValidationError(msg) from e
    if value < 0:
        msg = f"Row {row}: {field} cannot be negative."
        raise ValidationError(msg)
    return value.quantize(Decimal("0.01"))


def _parse_date(raw: str, *, row: int) -> date:
    """Parse due_date; accepts ISO and common Excel export formats (e.g. 2026/1/15)."""
    from datetime import datetime

    text = (raw or "").strip()
    if not text:
        msg = f"Row {row}: due_date is required for AR/AP aging rows."
        raise ValidationError(msg)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # Excel often writes 2026/1/15 (unpadded month/day) after opening the template.
    for sep in ("/", "-", "."):
        if sep not in text:
            continue
        parts = [p.strip() for p in text.split(sep)]
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        a, b, c = (int(parts[0]), int(parts[1]), int(parts[2]))
        if a > 31:
            y, m, d = a, b, c
        elif c > 31:
            if a > 12:
                d, m, y = a, b, c
            elif b > 12:
                m, d, y = a, b, c
            else:
                d, m, y = a, b, c
        else:
            continue
        try:
            return date(y, m, d)
        except ValueError:
            continue

    msg = (
        f"Row {row}: due_date '{raw}' is not a valid date "
        "(use YYYY-MM-DD, or a date Excel recognizes such as 2026/1/15)."
    )
    raise ValidationError(msg)


def _resolve_section(raw: str, *, row: int) -> str:
    key = (raw or "").strip().lower()
    if key not in _SECTION_ALIASES:
        allowed = ", ".join(sorted({v for v in _SECTION_ALIASES.values()}))
        msg = f"Row {row}: unknown section '{raw}'. Use one of: {allowed}."
        raise ValidationError(msg)
    return _SECTION_ALIASES[key]


def parse_opening_balance_csv(content: str | bytes) -> ParsedOpeningImport:
    """Parse US-7 CSV into structured sections."""
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = content.lstrip("\ufeff")

    if not text.strip():
        raise ValidationError("CSV file is empty.")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValidationError("CSV header row is missing.")

    normalized = {_normalize_header(h): h for h in reader.fieldnames if h}
    missing = [h for h in REQUIRED_HEADERS if h not in normalized]
    if missing:
        msg = f"CSV missing required columns: {', '.join(missing)}."
        raise ValidationError(msg)

    result = ParsedOpeningImport()
    for row_idx, raw_row in enumerate(reader, start=2):
        section_raw = raw_row.get(normalized["section"], "")
        if not (section_raw or "").strip() and not any(
            (raw_row.get(normalized[c], "") or "").strip()
            for c in REQUIRED_HEADERS
            if c != "section"
        ):
            continue

        section = _resolve_section(section_raw, row=row_idx)
        desc = (raw_row.get(normalized["description"], "") or "").strip()

        if section == "trial_balance":
            code = (raw_row.get(normalized["account_code"], "") or "").strip()
            if not code:
                msg = f"Row {row_idx}: account_code is required for trial_balance rows."
                raise ValidationError(msg)
            debit = _parse_decimal(
                raw_row.get(normalized["debit"], ""), row=row_idx, field="debit"
            )
            credit = _parse_decimal(
                raw_row.get(normalized["credit"], ""), row=row_idx, field="credit"
            )
            if debit > 0 and credit > 0:
                msg = f"Row {row_idx}: only one of debit or credit may be non-zero."
                raise ValidationError(msg)
            if debit == 0 and credit == 0:
                msg = f"Row {row_idx}: debit or credit must be non-zero."
                raise ValidationError(msg)
            result.trial_balance.append(
                TrialBalanceLine(
                    row_number=row_idx,
                    account_code=code,
                    debit=debit,
                    credit=credit,
                    description=desc,
                )
            )
        elif section == "ar_aging":
            name = (raw_row.get(normalized["counterparty_name"], "") or "").strip()
            if not name:
                msg = f"Row {row_idx}: counterparty_name is required for ar_aging rows."
                raise ValidationError(msg)
            amount = _parse_decimal(
                raw_row.get(normalized["amount"], ""), row=row_idx, field="amount"
            )
            if amount <= 0:
                msg = f"Row {row_idx}: amount must be greater than zero for ar_aging."
                raise ValidationError(msg)
            due = _parse_date(raw_row.get(normalized["due_date"], ""), row=row_idx)
            ref = (raw_row.get(normalized["reference"], "") or "").strip()
            if not ref:
                msg = f"Row {row_idx}: reference is required for ar_aging rows."
                raise ValidationError(msg)
            result.ar_aging.append(
                ArAgingLine(
                    row_number=row_idx,
                    customer_name=name,
                    amount=amount,
                    due_date=due,
                    reference=ref,
                    description=desc,
                )
            )
        else:  # ap_aging
            name = (raw_row.get(normalized["counterparty_name"], "") or "").strip()
            if not name:
                msg = f"Row {row_idx}: counterparty_name is required for ap_aging rows."
                raise ValidationError(msg)
            amount = _parse_decimal(
                raw_row.get(normalized["amount"], ""), row=row_idx, field="amount"
            )
            if amount <= 0:
                msg = f"Row {row_idx}: amount must be greater than zero for ap_aging."
                raise ValidationError(msg)
            due = _parse_date(raw_row.get(normalized["due_date"], ""), row=row_idx)
            ref_val = (raw_row.get(normalized["reference"], "") or "").strip()
            if not ref_val:
                msg = f"Row {row_idx}: reference is required for ap_aging rows."
                raise ValidationError(msg)
            result.ap_aging.append(
                ApAgingLine(
                    row_number=row_idx,
                    vendor_name=name,
                    amount=amount,
                    due_date=due,
                    reference=ref_val,
                    description=desc,
                )
            )

    if not result.trial_balance:
        raise ValidationError("CSV must include at least one trial_balance row.")

    return result
