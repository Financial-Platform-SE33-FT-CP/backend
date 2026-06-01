"""AR/AP API request/response schemas (US-8 invoicing)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ar_ap_service.modules.ar_ap.domain.entities import (
    Invoice,
    InvoiceSettlement,
    Payment,
    PaymentMethod,
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
