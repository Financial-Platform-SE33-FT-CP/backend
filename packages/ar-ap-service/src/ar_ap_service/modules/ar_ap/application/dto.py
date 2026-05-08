"""AR/AP DTOs."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class InvoiceDTO(BaseModel):
    """Invoice data transfer object."""

    id: UUID
    tenant_id: UUID | None = None
    customer_id: UUID | None = None
    invoice_number: str = ""
    amount: Decimal = Decimal("0.00")
    due_date: date | None = None
    status: str = "draft"
    created_at: datetime | None = None


class PaymentDTO(BaseModel):
    """Payment data transfer object."""

    id: UUID
    tenant_id: UUID | None = None
    invoice_id: UUID | None = None
    amount: Decimal = Decimal("0.00")
    payment_date: date | None = None
