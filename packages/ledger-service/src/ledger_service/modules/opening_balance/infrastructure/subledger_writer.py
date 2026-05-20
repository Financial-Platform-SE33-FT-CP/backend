"""Create opening AR/AP subledger documents (US-7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ar_ap_service.modules.ar_ap.infrastructure.models import (
    BillLineModel,
    BillModel,
    CustomerModel,
    InvoiceLineModel,
    InvoiceModel,
    VendorModel,
)

from ledger_service.modules.opening_balance.domain.entities import (
    ApAgingLine,
    ArAgingLine,
)
from ledger_service.modules.opening_balance.infrastructure.orm_registry import (
    register_opening_balance_orm_metadata,
)

register_opening_balance_orm_metadata()


class OpeningSubledgerWriter:
    """Persist opening invoices and bills linked to the opening journal entry."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_or_create_customer(
        self, tenant_id: uuid.UUID, name: str
    ) -> uuid.UUID:
        stmt = select(CustomerModel).where(
            CustomerModel.tenant_id == tenant_id,
            CustomerModel.name == name,
        )
        result = await self._session.execute(stmt)
        existing = result.scalars().first()
        if existing:
            return existing.id
        customer = CustomerModel(tenant_id=tenant_id, name=name)
        self._session.add(customer)
        await self._session.flush()
        return customer.id

    async def _get_or_create_vendor(
        self, tenant_id: uuid.UUID, name: str
    ) -> uuid.UUID:
        stmt = select(VendorModel).where(
            VendorModel.tenant_id == tenant_id,
            VendorModel.name == name,
        )
        result = await self._session.execute(stmt)
        existing = result.scalars().first()
        if existing:
            return existing.id
        vendor = VendorModel(tenant_id=tenant_id, name=name)
        self._session.add(vendor)
        await self._session.flush()
        return vendor.id

    async def create_ar_aging(
        self,
        *,
        tenant_id: str,
        journal_entry_id: str,
        lines: list[ArAgingLine],
        revenue_account_id: str,
    ) -> int:
        if not lines:
            return 0
        tid = uuid.UUID(tenant_id)
        rev_id = uuid.UUID(revenue_account_id)
        count = 0
        for line in lines:
            customer_id = await self._get_or_create_customer(tid, line.customer_name)
            invoice = InvoiceModel(
                tenant_id=tid,
                customer_id=customer_id,
                invoice_number=line.reference,
                amount=line.amount,
                issue_date=line.due_date,
                due_date=line.due_date,
                subtotal=line.amount,
                gst_amount=Decimal("0"),
                total=line.amount,
                journal_entry_id=journal_entry_id,
                status="opening",
                created_at=datetime.utcnow(),
            )
            self._session.add(invoice)
            await self._session.flush()
            inv_line = InvoiceLineModel(
                invoice_id=invoice.id,
                description=line.description or "Opening balance",
                quantity=Decimal("1"),
                unit_price=line.amount,
                account_id=rev_id,
                gst_rate=Decimal("0"),
                line_total=line.amount,
            )
            self._session.add(inv_line)
            count += 1
        return count

    async def create_ap_aging(
        self,
        *,
        tenant_id: str,
        journal_entry_id: str,
        lines: list[ApAgingLine],
        expense_account_id: str,
    ) -> int:
        if not lines:
            return 0
        tid = uuid.UUID(tenant_id)
        exp_id = uuid.UUID(expense_account_id)
        count = 0
        for line in lines:
            vendor_id = await self._get_or_create_vendor(tid, line.vendor_name)
            bill = BillModel(
                tenant_id=tid,
                vendor_id=vendor_id,
                bill_number=line.reference,
                issue_date=line.due_date,
                due_date=line.due_date,
                status="opening",
                subtotal=line.amount,
                gst_amount=Decimal("0"),
                total=line.amount,
                journal_entry_id=journal_entry_id,
                created_at=datetime.utcnow(),
            )
            self._session.add(bill)
            await self._session.flush()
            bill_line = BillLineModel(
                bill_id=bill.id,
                description=line.description or "Opening balance",
                account_id=exp_id,
                amount=line.amount,
                gst_rate=Decimal("0"),
            )
            self._session.add(bill_line)
            count += 1
        return count
