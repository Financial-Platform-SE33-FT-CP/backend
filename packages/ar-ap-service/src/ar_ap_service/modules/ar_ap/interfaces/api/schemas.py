"""AR/AP API schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class InvoiceResponse(BaseModel):
    """Invoice response schema."""

    id: UUID
    tenant_id: UUID | None = None
    customer_id: UUID | None = None
    invoice_number: str
    amount: Decimal
    due_date: date | None = None
    status: str
    created_at: datetime | None = None


class PaymentResponse(BaseModel):
    """Payment response schema."""

    id: UUID
    tenant_id: UUID | None = None
    invoice_id: UUID | None = None
    amount: Decimal
    payment_date: date | None = None
