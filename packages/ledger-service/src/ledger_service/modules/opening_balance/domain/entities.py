"""Domain entities for opening balance CSV import (US-7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class TrialBalanceLine:
    row_number: int
    account_code: str
    debit: Decimal
    credit: Decimal
    description: str = ""


@dataclass(frozen=True)
class ArAgingLine:
    row_number: int
    customer_name: str
    amount: Decimal
    due_date: date
    reference: str
    description: str = ""


@dataclass(frozen=True)
class ApAgingLine:
    row_number: int
    vendor_name: str
    amount: Decimal
    due_date: date
    reference: str
    description: str = ""


@dataclass
class ParsedOpeningImport:
    trial_balance: list[TrialBalanceLine] = field(default_factory=list)
    ar_aging: list[ArAgingLine] = field(default_factory=list)
    ap_aging: list[ApAgingLine] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationIssue:
    row: int | None
    field: str
    message: str


@dataclass
class OpeningImportPreview:
    total_debit: Decimal
    total_credit: Decimal
    trial_balance_line_count: int
    ar_aging_line_count: int
    ap_aging_line_count: int
    ar_aging_total: Decimal
    ap_aging_total: Decimal
    resolved_accounts: dict[str, str]  # code -> account_id


@dataclass(frozen=True)
class ResolvedTrialLine:
    account_id: str
    account_code: str
    debit: Decimal
    credit: Decimal
    description: str
