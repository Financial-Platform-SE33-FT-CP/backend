from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4


@dataclass
class JournalEntryLine:
    id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    journal_entry_id: str = ""
    account_id: str = ""
    debit_amount: Decimal = field(default_factory=Decimal)
    credit_amount: Decimal = field(default_factory=Decimal)
    description: str = ""

    @property
    def is_debit(self) -> bool:
        return self.debit_amount > 0

    @property
    def is_credit(self) -> bool:
        return self.credit_amount > 0

    @property
    def net_amount(self) -> Decimal:
        return self.debit_amount - self.credit_amount


@dataclass
class JournalEntry:
    id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = ""
    entry_date: date = field(default_factory=date.today)
    reference: str = ""
    description: str = ""
    source_type: str = "manual"
    source_id: str | None = None
    created_by: str = ""
    is_reversal: bool = False
    reversed_entry_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    lines: list[JournalEntryLine] = field(default_factory=list)

    @property
    def total_debit(self) -> Decimal:
        return sum(
            (line.debit_amount for line in self.lines), Decimal("0.00")
        )

    @property
    def total_credit(self) -> Decimal:
        return sum(
            (line.credit_amount for line in self.lines), Decimal("0.00")
        )

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def has_lines(self) -> bool:
        return len(self.lines) >= 2


@dataclass
class AccountingPeriod:
    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID = field(default_factory=uuid4)
    start_date: date = field(default_factory=date.today)
    end_date: date = field(default_factory=date.today)
    is_closed: bool = False
    closed_by: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def contains(self, target_date: date) -> bool:
        return self.start_date <= target_date <= self.end_date
