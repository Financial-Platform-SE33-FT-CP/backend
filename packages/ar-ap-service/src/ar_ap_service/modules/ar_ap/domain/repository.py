"""AR/AP repository interfaces."""

from abc import ABC, abstractmethod
from uuid import UUID

from ar_ap_service.modules.ar_ap.domain.entities import Invoice, Payment


class InvoiceRepository(ABC):
    """Repository interface for invoices."""

    @abstractmethod
    async def get_by_id(self, invoice_id: UUID) -> Invoice | None:
        ...

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> list[Invoice]:
        ...

    @abstractmethod
    async def create(self, invoice: Invoice) -> Invoice:
        ...


class PaymentRepository(ABC):
    """Repository interface for payments."""

    @abstractmethod
    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        ...

    @abstractmethod
    async def list_by_invoice(self, invoice_id: UUID) -> list[Payment]:
        ...

    @abstractmethod
    async def create(self, payment: Payment) -> Payment:
        ...
