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


class PaymentMethod(StrEnum):
    """How a customer settled an invoice (US-9)."""

    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    CHEQUE = "cheque"
    CARD = "card"
    OTHER = "other"


@dataclass
class Payment:
    """A customer payment recorded against a single issued invoice (US-9).

    A payment is immutable once posted: it always carries the id of the balanced
    journal entry (Debit bank/cash, Credit Accounts Receivable) created alongside
    it. Corrections are made via reversals/credit notes, never by editing.
    """

    invoice_id: UUID
    amount: Decimal
    deposit_account_id: UUID | None
    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    customer_id: UUID | None = None
    payment_date: date | None = None
    payment_method: PaymentMethod = PaymentMethod.BANK_TRANSFER
    reference: str | None = None
    journal_entry_id: str | None = None
    idempotency_key: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class InvoiceSettlement:
    """Snapshot of how much of an invoice has been settled by posted payments."""

    invoice_total: Decimal
    amount_paid: Decimal

    @property
    def outstanding(self) -> Decimal:
        """Remaining balance still owed on the invoice (never below zero)."""
        remaining = self.invoice_total - self.amount_paid
        return remaining if remaining > _ZERO else _ZERO


class CreditNoteStatus(StrEnum):
    """Lifecycle of a credit note (US-10).

    A credit note is posted as ``ISSUED`` and is immutable thereafter. ``VOIDED``
    is reserved for a future void/reverse flow and is not produced by US-10.
    """

    ISSUED = "issued"
    VOIDED = "voided"


@dataclass
class CreditNoteLine:
    """A single line on a credit note that reverses/reduces invoice revenue.

    ``line_total`` is the net (pre-GST) amount being credited; ``gst_amount`` is
    the GST being reversed on that line. Both are derived on the backend from
    quantity, unit price and GST rate — the client never supplies totals.
    """

    account_id: UUID
    quantity: Decimal
    unit_price: Decimal
    description: str | None = None
    gst_rate: Decimal = _ZERO
    invoice_line_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    credit_note_id: UUID | None = None
    line_total: Decimal = _ZERO
    gst_amount: Decimal = _ZERO

    def recalculate(self) -> None:
        """Recompute ``line_total`` and ``gst_amount`` from quantity/price/rate."""
        net = _money(self.quantity * self.unit_price)
        self.line_total = net
        self.gst_amount = _money(net * (self.gst_rate or _ZERO))


@dataclass
class CreditNote:
    """A credit note issued against an existing issued invoice (US-10).

    Issuing a credit note posts a balanced reversal/adjustment journal entry
    (Debit Revenue, Debit GST Output, Credit Accounts Receivable) and is
    immutable once posted: it always carries the id of that journal entry.
    Corrections to issued invoices are made through credit notes, never by
    editing the original invoice or its journal entry.
    """

    invoice_id: UUID
    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    customer_id: UUID | None = None
    credit_note_number: str = ""
    issue_date: date | None = None
    reason: str | None = None
    status: CreditNoteStatus = CreditNoteStatus.ISSUED
    subtotal: Decimal = _ZERO
    gst_amount: Decimal = _ZERO
    total: Decimal = _ZERO
    journal_entry_id: str | None = None
    idempotency_key: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    lines: list[CreditNoteLine] = field(default_factory=list)

    def recalculate_totals(self) -> None:
        """Recompute line amounts and roll them up into credit-note-level totals."""
        subtotal = _ZERO
        gst = _ZERO
        for line in self.lines:
            line.recalculate()
            subtotal += line.line_total
            gst += line.gst_amount
        self.subtotal = _money(subtotal)
        self.gst_amount = _money(gst)
        self.total = _money(self.subtotal + self.gst_amount)


class BillStatus(StrEnum):
    """Lifecycle of a vendor bill (US-11 / US-12)."""

    DRAFT = "draft"
    OPEN = "open"
    PARTIAL = "partial"
    PAID = "paid"
    VOID = "void"


POSTED_BILL_STATUSES: frozenset[BillStatus] = frozenset(
    {
        BillStatus.OPEN,
        BillStatus.PARTIAL,
        BillStatus.PAID,
    }
)


@dataclass
class BillLine:
    """A single line on a vendor bill."""

    account_id: UUID
    quantity: Decimal
    unit_price: Decimal
    description: str | None = None
    gst_rate: Decimal = _ZERO
    id: UUID = field(default_factory=uuid4)
    bill_id: UUID | None = None
    line_total: Decimal = _ZERO
    gst_amount: Decimal = _ZERO

    def recalculate(self) -> None:
        net = _money(self.quantity * self.unit_price)
        self.line_total = net
        self.gst_amount = _money(net * (self.gst_rate or _ZERO))


@dataclass
class Bill:
    """A vendor bill aggregate with its lines."""

    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    vendor_id: UUID | None = None
    bill_number: str = ""
    issue_date: date | None = None
    due_date: date | None = None
    status: BillStatus = BillStatus.DRAFT
    subtotal: Decimal = _ZERO
    gst_amount: Decimal = _ZERO
    total: Decimal = _ZERO
    journal_entry_id: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None
    lines: list[BillLine] = field(default_factory=list)

    @property
    def is_posted(self) -> bool:
        return self.status in POSTED_BILL_STATUSES

    def recalculate_totals(self) -> None:
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
class Vendor:
    """A tenant's vendor (bill counterparty)."""

    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    name: str = ""
    email: str | None = None


@dataclass
class BillPayment:
    """A payment recorded against a posted vendor bill (US-12)."""

    bill_id: UUID
    amount: Decimal
    payment_account_id: UUID | None
    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    vendor_id: UUID | None = None
    payment_date: date | None = None
    payment_method: PaymentMethod = PaymentMethod.BANK_TRANSFER
    reference: str | None = None
    journal_entry_id: str | None = None
    idempotency_key: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class BillSettlement:
    """Snapshot of how much of a bill has been paid."""

    bill_total: Decimal
    amount_paid: Decimal

    @property
    def outstanding(self) -> Decimal:
        remaining = self.bill_total - self.amount_paid
        return remaining if remaining > _ZERO else _ZERO


@dataclass(frozen=True)
class APAgingLine:
    """One open bill row for AP aging (US-12)."""

    bill_id: UUID
    vendor_id: UUID | None
    bill_number: str
    due_date: date | None
    bill_total: Decimal
    amount_paid: Decimal
    outstanding: Decimal
    days_overdue: int
    aging_bucket: str
