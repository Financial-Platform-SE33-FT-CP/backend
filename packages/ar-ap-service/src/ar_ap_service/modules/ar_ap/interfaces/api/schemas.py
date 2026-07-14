"""AR/AP API request/response schemas (US-8 invoicing)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ar_ap_service.modules.ar_ap.domain.entities import (
    BankAccount,
    BankTransaction,
    Bill,
    BillLine,
    BillPayment,
    BillSettlement,
    CreditNote,
    Invoice,
    InvoiceSettlement,
    Payment,
    PaymentMethod,
    ReconciliationSuggestion,
    Vendor,
)


class InvoiceLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    description: str | None = None
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0)


class CreateInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    issue_date: date
    due_date: date
    lines: list[InvoiceLineRequest] = Field(min_length=1)


class UpdateInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID | None = None
    issue_date: date | None = None
    due_date: date | None = None
    lines: list[InvoiceLineRequest] | None = Field(default=None, min_length=1)


class InvoiceLineResponse(BaseModel):
    id: UUID
    account_id: UUID
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    line_total: Decimal
    gst_amount: Decimal


class InvoiceResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    customer_id: UUID | None
    invoice_number: str
    issue_date: date | None
    due_date: date | None
    status: str
    subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    journal_entry_id: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime | None
    lines: list[InvoiceLineResponse]

    @classmethod
    def from_entity(cls, invoice: Invoice) -> InvoiceResponse:
        return cls(
            id=invoice.id,
            tenant_id=invoice.tenant_id,
            customer_id=invoice.customer_id,
            invoice_number=invoice.invoice_number,
            issue_date=invoice.issue_date,
            due_date=invoice.due_date,
            status=invoice.status.value,
            subtotal=invoice.subtotal,
            gst_amount=invoice.gst_amount,
            total=invoice.total,
            journal_entry_id=invoice.journal_entry_id,
            created_by=invoice.created_by,
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
            lines=[
                InvoiceLineResponse(
                    id=line.id,
                    account_id=line.account_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    gst_rate=line.gst_rate,
                    line_total=line.line_total,
                    gst_amount=line.gst_amount,
                )
                for line in invoice.lines
            ],
        )


class CreateCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    credit_terms_days: int | None = Field(default=None, ge=0)


class CustomerResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    name: str
    email: str | None
    credit_terms_days: int | None


class RecordPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_date: date
    amount: Decimal = Field(gt=0)
    payment_method: PaymentMethod = PaymentMethod.BANK_TRANSFER
    reference: str | None = Field(default=None, max_length=255)
    deposit_account_id: UUID
    idempotency_key: str | None = Field(default=None, max_length=255)


class PaymentResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    invoice_id: UUID
    customer_id: UUID | None
    amount: Decimal
    payment_date: date | None
    payment_method: str
    reference: str | None
    deposit_account_id: UUID | None
    journal_entry_id: str | None
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_entity(cls, payment: Payment) -> PaymentResponse:
        return cls(
            id=payment.id,
            tenant_id=payment.tenant_id,
            invoice_id=payment.invoice_id,
            customer_id=payment.customer_id,
            amount=payment.amount,
            payment_date=payment.payment_date,
            payment_method=payment.payment_method.value,
            reference=payment.reference,
            deposit_account_id=payment.deposit_account_id,
            journal_entry_id=payment.journal_entry_id,
            created_by=payment.created_by,
            created_at=payment.created_at,
        )


class InvoiceSettlementResponse(BaseModel):
    invoice_id: UUID
    invoice_total: Decimal
    amount_paid: Decimal
    outstanding: Decimal

    @classmethod
    def from_entity(
        cls, invoice_id: UUID, settlement: InvoiceSettlement
    ) -> InvoiceSettlementResponse:
        return cls(
            invoice_id=invoice_id,
            invoice_total=settlement.invoice_total,
            amount_paid=settlement.amount_paid,
            outstanding=settlement.outstanding,
        )


class CreditNoteLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    description: str | None = None
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0)
    invoice_line_id: UUID | None = None


class IssueCreditNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_date: date
    reason: str | None = Field(default=None, max_length=500)
    lines: list[CreditNoteLineRequest] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=255)


class CreditNoteLineResponse(BaseModel):
    id: UUID
    account_id: UUID
    invoice_line_id: UUID | None
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    line_total: Decimal
    gst_amount: Decimal


class CreditNoteResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    invoice_id: UUID
    customer_id: UUID | None
    credit_note_number: str
    issue_date: date | None
    reason: str | None
    status: str
    subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    journal_entry_id: str | None
    created_by: UUID | None
    created_at: datetime
    lines: list[CreditNoteLineResponse]

    @classmethod
    def from_entity(cls, credit_note: CreditNote) -> CreditNoteResponse:
        return cls(
            id=credit_note.id,
            tenant_id=credit_note.tenant_id,
            invoice_id=credit_note.invoice_id,
            customer_id=credit_note.customer_id,
            credit_note_number=credit_note.credit_note_number,
            issue_date=credit_note.issue_date,
            reason=credit_note.reason,
            status=credit_note.status.value,
            subtotal=credit_note.subtotal,
            gst_amount=credit_note.gst_amount,
            total=credit_note.total,
            journal_entry_id=credit_note.journal_entry_id,
            created_by=credit_note.created_by,
            created_at=credit_note.created_at,
            lines=[
                CreditNoteLineResponse(
                    id=line.id,
                    account_id=line.account_id,
                    invoice_line_id=line.invoice_line_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    gst_rate=line.gst_rate,
                    line_total=line.line_total,
                    gst_amount=line.gst_amount,
                )
                for line in credit_note.lines
            ],
        )


class CreateBankAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    account_number: str | None = Field(default=None, max_length=64)
    currency: str = Field(default="SGD", max_length=3)
    opening_balance: Decimal = Field(default=Decimal("0.00"))


class BankAccountResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    name: str
    account_number: str | None
    currency: str
    opening_balance: Decimal

    @classmethod
    def from_entity(cls, acct: BankAccount) -> BankAccountResponse:
        return cls(
            id=acct.id,
            tenant_id=acct.tenant_id,
            name=acct.name,
            account_number=acct.account_number,
            currency=acct.currency,
            opening_balance=acct.opening_balance,
        )


class UploadBankStatementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_account_id: UUID
    csv_content: str = Field(min_length=1)


class BankTransactionResponse(BaseModel):
    id: UUID
    bank_account_id: UUID
    transaction_date: date
    description: str | None
    amount: Decimal
    matched: bool
    journal_entry_id: str | None
    checksum_hash: str | None
    upload_batch_id: UUID | None
    reconciliation_entity_type: str | None
    reconciliation_entity_id: UUID | None
    created_at: datetime

    @classmethod
    def from_entity(cls, txn: BankTransaction) -> BankTransactionResponse:
        ba_id = txn.bank_account_id or UUID("00000000-0000-0000-0000-000000000000")
        txn_date = txn.transaction_date or date.today()
        return cls(
            id=txn.id,
            bank_account_id=ba_id,
            transaction_date=txn_date,
            description=txn.description,
            amount=txn.amount,
            matched=txn.matched,
            journal_entry_id=txn.journal_entry_id,
            checksum_hash=txn.checksum_hash,
            upload_batch_id=txn.upload_batch_id,
            reconciliation_entity_type=txn.reconciliation_entity_type,
            reconciliation_entity_id=txn.reconciliation_entity_id,
            created_at=txn.created_at,
        )


class ReconcileTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: UUID
    match_type: str = Field(pattern=r"^(invoice|payment|bill|other)$")
    match_id: UUID | None = None
    account_id: UUID


class ReconciliationSuggestionResponse(BaseModel):
    bank_transaction_id: UUID
    match_type: str
    match_id: UUID
    match_label: str
    match_amount: Decimal
    difference: Decimal
    confidence: str

    @classmethod
    def from_entity(cls, s: ReconciliationSuggestion) -> ReconciliationSuggestionResponse:
        return cls(
            bank_transaction_id=s.bank_transaction_id,
            match_type=s.match_type,
            match_id=s.match_id,
            match_label=s.match_label,
            match_amount=s.match_amount,
            difference=s.difference,
            confidence=s.confidence,
        )


# ── bills / AP (US-11 / US-12) ────────────────────────────────────────────────


class BillLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    description: str | None = None
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0)


class CreateBillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_id: UUID
    issue_date: date
    due_date: date
    lines: list[BillLineRequest] = Field(min_length=1)


class UpdateBillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_id: UUID | None = None
    issue_date: date | None = None
    due_date: date | None = None
    lines: list[BillLineRequest] | None = Field(default=None, min_length=1)


class BillLineResponse(BaseModel):
    id: UUID
    account_id: UUID
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    line_total: Decimal
    gst_amount: Decimal


class BillResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    vendor_id: UUID | None
    bill_number: str
    issue_date: date | None
    due_date: date | None
    status: str
    subtotal: Decimal
    gst_amount: Decimal
    total: Decimal
    journal_entry_id: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime | None
    lines: list[BillLineResponse]

    @classmethod
    def from_entity(cls, bill: Bill) -> BillResponse:
        return cls(
            id=bill.id,
            tenant_id=bill.tenant_id,
            vendor_id=bill.vendor_id,
            bill_number=bill.bill_number,
            issue_date=bill.issue_date,
            due_date=bill.due_date,
            status=bill.status.value,
            subtotal=bill.subtotal,
            gst_amount=bill.gst_amount,
            total=bill.total,
            journal_entry_id=bill.journal_entry_id,
            created_by=bill.created_by,
            created_at=bill.created_at,
            updated_at=bill.updated_at,
            lines=[
                BillLineResponse(
                    id=line.id,
                    account_id=line.account_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    gst_rate=line.gst_rate,
                    line_total=line.line_total,
                    gst_amount=line.gst_amount,
                )
                for line in bill.lines
            ],
        )


class CreateVendorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    email: str | None = None


class VendorResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    name: str
    email: str | None

    @classmethod
    def from_entity(cls, v: Vendor) -> VendorResponse:
        return cls(
            id=v.id,
            tenant_id=v.tenant_id,
            name=v.name,
            email=v.email,
        )


class PayBillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_date: date
    amount: Decimal = Field(gt=0)
    payment_method: str
    reference: str | None = None
    payment_account_id: UUID


class BillPaymentResponse(BaseModel):
    id: UUID
    tenant_id: UUID | None
    bill_id: UUID
    vendor_id: UUID | None
    amount: Decimal
    payment_date: date | None
    payment_method: str
    reference: str | None
    payment_account_id: UUID | None
    journal_entry_id: str | None
    created_by: UUID | None
    created_at: datetime

    @classmethod
    def from_entity(cls, payment: BillPayment) -> BillPaymentResponse:
        return cls(
            id=payment.id,
            tenant_id=payment.tenant_id,
            bill_id=payment.bill_id,
            vendor_id=payment.vendor_id,
            amount=payment.amount,
            payment_date=payment.payment_date,
            payment_method=payment.payment_method.value,
            reference=payment.reference,
            payment_account_id=payment.payment_account_id,
            journal_entry_id=payment.journal_entry_id,
            created_by=payment.created_by,
            created_at=payment.created_at,
        )


class BillSettlementResponse(BaseModel):
    bill_id: UUID
    bill_total: Decimal
    amount_paid: Decimal
    outstanding: Decimal

    @classmethod
    def from_entity(cls, bill_id: UUID, total: Decimal, paid: Decimal) -> BillSettlementResponse:
        settlement = BillSettlement(bill_total=total, amount_paid=paid)
        return cls(
            bill_id=bill_id,
            bill_total=settlement.bill_total,
            amount_paid=settlement.amount_paid,
            outstanding=settlement.outstanding,
        )


class APAgingLineResponse(BaseModel):
    bill_id: UUID
    vendor_id: str | None
    bill_number: str
    due_date: str | None
    bill_total: str
    amount_paid: str
    outstanding: str
    days_overdue: int
    aging_bucket: str
