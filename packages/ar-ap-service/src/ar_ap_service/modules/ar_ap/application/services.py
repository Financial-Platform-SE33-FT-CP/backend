"""AR/AP application services."""

from uuid import UUID

from ar_ap_service.modules.ar_ap.domain.entities import Invoice, Payment
from ar_ap_service.modules.ar_ap.domain.repository import (
    InvoiceRepository,
    PaymentRepository,
)


class ArApService:
    """Application service for AR/AP operations."""

    def __init__(
        self,
        invoice_repo: InvoiceRepository,
        payment_repo: PaymentRepository,
    ) -> None:
        self._invoice_repo = invoice_repo
        self._payment_repo = payment_repo

    async def create_invoice(self, invoice: Invoice) -> Invoice:
        """Create a new invoice."""
        raise NotImplementedError

    async def get_invoice(self, invoice_id: UUID) -> Invoice | None:
        """Get an invoice by ID."""
        raise NotImplementedError

    async def record_payment(self, payment: Payment) -> Payment:
        """Record a payment against an invoice."""
        raise NotImplementedError

    async def get_invoice_payments(self, invoice_id: UUID) -> list[Payment]:
        """Get all payments for an invoice."""
        raise NotImplementedError
