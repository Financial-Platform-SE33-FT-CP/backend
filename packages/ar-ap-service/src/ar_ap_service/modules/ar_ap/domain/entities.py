"""AR/AP domain entities."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4


@dataclass
class Invoice:
    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    customer_id: UUID | None = None
    invoice_number: str = ""
    amount: Decimal = Decimal("0.00")
    due_date: date | None = None
    status: str = "draft"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Payment:
    id: UUID = field(default_factory=uuid4)
    tenant_id: UUID | None = None
    invoice_id: UUID | None = None
    amount: Decimal = Decimal("0.00")
    payment_date: date | None = None
