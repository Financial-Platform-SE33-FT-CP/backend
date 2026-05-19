from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4


@dataclass
class JournalEntry:
    id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    entry_date: date = field(default_factory=date.today)
    reference: str = ""
    description: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class JournalEntryLine:
    id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    journal_entry_id: str = ""
    account_id: str = ""
    debit_amount: Decimal = field(default_factory=Decimal)
    credit_amount: Decimal = field(default_factory=Decimal)
    description: str = ""


@dataclass(frozen=True)
class LedgerAccountSnapshot:
    id: str
    code: str
    name: str
    account_type: str


@dataclass(frozen=True)
class AccountLedgerTransaction:
    journal_line_id: str
    journal_entry_id: str
    entry_date: date
    reference: str
    source_type: str | None
    entry_description: str | None
    line_description: str | None
    debit_amount: Decimal
    credit_amount: Decimal
    created_at: datetime


@dataclass(frozen=True)
class TrialBalanceAccountAggregate:
    account_id: str
    account_code: str
    account_name: str
    account_type: str
    total_debit: Decimal
    total_credit: Decimal