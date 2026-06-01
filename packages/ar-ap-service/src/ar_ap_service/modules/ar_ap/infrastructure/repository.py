"""SQLAlchemy AR/AP repository implementations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ar_ap_service.modules.ar_ap.domain.entities import Invoice, Payment
from ar_ap_service.modules.ar_ap.domain.repository import (
    InvoiceRepository,
    PaymentRepository,
)
from ar_ap_service.modules.ar_ap.infrastructure.models import InvoiceModel, PaymentModel


class SqlAlchemyInvoiceRepository(InvoiceRepository):
    """SQLAlchemy implementation of InvoiceRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, invoice_id: UUID) -> Invoice | None:
        raise NotImplementedError

    async def list_by_tenant(self, tenant_id: UUID) -> list[Invoice]:
        raise NotImplementedError

    async def create(self, invoice: Invoice) -> Invoice:
        raise NotImplementedError


class SqlAlchemyPaymentRepository(PaymentRepository):
    """SQLAlchemy implementation of PaymentRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        raise NotImplementedError

    async def list_by_invoice(self, invoice_id: UUID) -> list[Payment]:
        raise NotImplementedError

    async def create(self, payment: Payment) -> Payment:
        raise NotImplementedError
