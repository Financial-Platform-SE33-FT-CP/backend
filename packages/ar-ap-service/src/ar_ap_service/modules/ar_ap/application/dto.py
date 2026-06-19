"""AR/AP application DTOs (commands passed from the API into the service)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ar_ap_service.modules.ar_ap.domain.entities import PaymentMethod


class InvoiceLineInput(BaseModel):
    """A single invoice line supplied by the client."""

    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    description: str | None = None
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0)


class CreateInvoiceCommand(BaseModel):
    """Payload for creating a draft invoice.

    ``tenant_id`` is intentionally absent: it is always derived from the
    authenticated request context, never trusted from the client.
    """

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    issue_date: date
    due_date: date
    lines: list[InvoiceLineInput] = Field(min_length=1)


class UpdateInvoiceCommand(BaseModel):
    """Payload for updating a draft invoice (full replacement of editable fields)."""

    model_config = ConfigDict(extra="forbid")

    customer_id: UUID | None = None
    issue_date: date | None = None
    due_date: date | None = None
    lines: list[InvoiceLineInput] | None = Field(default=None, min_length=1)


class RecordPaymentCommand(BaseModel):
    """Payload for recording a customer payment against an issued invoice (US-9).

    ``tenant_id`` and ``customer_id`` are intentionally absent: tenant comes from
    the authenticated context and the customer is derived from the invoice. The
    backend computes the outstanding balance; the client never supplies it.
    """

    model_config = ConfigDict(extra="forbid")

    payment_date: date
    amount: Decimal = Field(gt=0)
    payment_method: PaymentMethod = PaymentMethod.BANK_TRANSFER
    reference: str | None = Field(default=None, max_length=255)
    deposit_account_id: UUID
    idempotency_key: str | None = Field(default=None, max_length=255)


class CreditNoteLineInput(BaseModel):
    """A single credit note line supplied by the client (US-10).

    ``line_total`` and ``gst_amount`` are intentionally absent: the backend
    computes them from quantity, unit price and GST rate so frontend totals are
    never trusted.
    """

    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    description: str | None = None
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0)
    invoice_line_id: UUID | None = None


class BillLineInput(BaseModel):
    """A single bill line supplied by the client (US-11)."""

    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    description: str | None = None
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0)


class CreateBillCommand(BaseModel):
    """Payload for creating a draft vendor bill."""

    model_config = ConfigDict(extra="forbid")

    vendor_id: UUID
    issue_date: date
    due_date: date
    lines: list[BillLineInput] = Field(min_length=1)


class UpdateBillCommand(BaseModel):
    """Payload for updating a draft vendor bill."""

    model_config = ConfigDict(extra="forbid")

    vendor_id: UUID | None = None
    issue_date: date | None = None
    due_date: date | None = None
    lines: list[BillLineInput] | None = Field(default=None, min_length=1)


class PayBillCommand(BaseModel):
    """Payload for paying a posted vendor bill (US-12)."""

    model_config = ConfigDict(extra="forbid")

    payment_date: date
    amount: Decimal = Field(gt=0)
    payment_method: PaymentMethod = PaymentMethod.BANK_TRANSFER
    reference: str | None = Field(default=None, max_length=255)
    payment_account_id: UUID
    idempotency_key: str | None = Field(default=None, max_length=255)


class IssueCreditNoteCommand(BaseModel):
    """Payload for issuing a credit note against an issued invoice (US-10).

    ``tenant_id`` and ``customer_id`` are intentionally absent: tenant comes from
    the authenticated context and the customer is derived from the invoice. The
    backend computes subtotal, GST and total; the client never supplies them.
    """

    model_config = ConfigDict(extra="forbid")

    issue_date: date
    reason: str | None = Field(default=None, max_length=500)
    lines: list[CreditNoteLineInput] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, max_length=255)
