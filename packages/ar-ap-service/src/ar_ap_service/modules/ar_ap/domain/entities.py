"""AR/AP domain entities (US-8 invoicing)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID, uuid4

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value: Decimal) -> Decimal:
    """Round a monetary value to 2 decimal places (banker-safe half-up)."""
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


class InvoiceStatus(StrEnum):
    """Lifecycle of a customer invoice."""

    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    PARTIAL = "partial"
    OVERDUE = "overdue"


#: Statuses for which the invoice has been posted to the ledger and is immutable.
POSTED_STATUSES: frozenset[InvoiceStatus] = frozenset(
    {
        InvoiceStatus.ISSUED,
        InvoiceStatus.PAID,
        InvoiceStatus.PARTIAL,
        InvoiceStatus.OVERDUE,
    }
)


@dataclass
class InvoiceLine:
    """A single billable line on an invoice.

    ``line_total`` is the net (pre-GST) amount; ``gst_amount`` is the tax on that
    line. Both are derived from quantity, unit price and GST rate.
    """

    account_id: UUID
    quantity: Decimal
    unit_price: Decimal
    description: str | None = None
    gst_rate: Decimal = _ZERO
    id: UUID = field(default_factory=uuid4)
    invoice_id: UUID | None = None
    line_total: Decimal = _ZERO
    gst_amount: Decimal = _ZERO

    def recalculate(self) -> None:
        """Recompute ``line_total`` and ``gst_amount`` from quantity/price/rate."""
        net = _money(self.quantity * self.unit_price)
        self.line_total = net
        self.gst_amount = _money(net * (self.gst_rate or _ZERO))


@dataclass
class Invoice:
    """A customer invoice aggregate with its lines."""

    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    customer_id: UUID | None = None
    invoice_number: str = ""
    issue_date: date | None = None
    due_date: date | None = None
    status: InvoiceStatus = InvoiceStatus.DRAFT
    subtotal: Decimal = _ZERO
    gst_amount: Decimal = _ZERO
    total: Decimal = _ZERO
    journal_entry_id: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None
    lines: list[InvoiceLine] = field(default_factory=list)

    @property
    def is_posted(self) -> bool:
        """True once the invoice has been issued/posted to the ledger."""
        return self.status in POSTED_STATUSES

    def recalculate_totals(self) -> None:
        """Recompute line amounts and roll them up into invoice-level totals."""
        subtotal = _ZERO
        gst = _ZERO
        for line in self.lines:
            line.recalculate()
            subtotal += line.line_total
            gst += line.gst_amount
        self.subtotal = _money(subtotal)
        self.gst_amount = _money(gst)
        self.total = _money(self.subtotal + self.gst_amount)


@dataclass
class Customer:
    """A tenant's customer (invoice counterparty)."""

    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    name: str = ""
    email: str | None = None
    credit_terms_days: int | None = None


@dataclass(frozen=True)
class AccountInfo:
    """Minimal chart-of-accounts snapshot used for invoice validation."""

    id: UUID
    code: str
    name: str
    account_type: str
    is_active: bool


@dataclass(frozen=True)
class JournalLineInput:
    """One line to post into the immutable ledger when issuing an invoice."""

    account_id: str
    debit_amount: Decimal = _ZERO
    credit_amount: Decimal = _ZERO
    description: str | None = None
