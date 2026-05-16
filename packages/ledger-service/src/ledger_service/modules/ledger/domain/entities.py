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
