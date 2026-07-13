"""SQLAlchemy AR/AP infrastructure: invoice/customer repos, COA reader, ledger poster.

Cross-service tables (chart_of_accounts, accounting_periods, journal_entries) are
owned by other services. We read/write them with explicit SQL through the shared
database so AR/AP does not import those services' ORM models (which would create a
circular dependency with ledger-service). Everything runs on the caller's session
so issuing an invoice and posting its journal entry commit atomically.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import RowMapping, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    Bill,
    BillLine,
    BillPayment,
    BillStatus,
    CreditNote,
    CreditNoteLine,
    CreditNoteStatus,
    Customer,
    GstCode,
    GstKind,
    GstSourceType,
    GstTransaction,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    JournalLineInput,
    Payment,
    PaymentMethod,
    Vendor,
)
from ar_ap_service.modules.ar_ap.domain.repository import (
    AccountReader,
    BillPaymentRepository,
    BillRepository,
    CreditNoteRepository,
    CustomerRepository,
    GstRepository,
    InvoiceRepository,
    LedgerPoster,
    PaymentRepository,
    VendorRepository,
)
from ar_ap_service.modules.ar_ap.infrastructure.models import (
    BillLineModel,
    BillModel,
    BillPaymentModel,
    CreditNoteLineModel,
    CreditNoteModel,
    CustomerModel,
    InvoiceLineModel,
    InvoiceModel,
    GstCodeModel,
    GstTransactionModel,
    PaymentModel,
    VendorModel,
)

_ZERO = Decimal("0.00")

# chart_of_accounts.type may be stored as enum value ("revenue") or legacy name ("REVENUE").
_ACCOUNT_TYPE_ALIASES: dict[str, str] = {
    "asset": "asset",
    "liability": "liability",
    "equity": "equity",
    "revenue": "revenue",
    "expense": "expense",
    "ASSET": "asset",
    "LIABILITY": "liability",
    "EQUITY": "equity",
    "REVENUE": "revenue",
    "EXPENSE": "expense",
}


def _normalize_account_type(raw: str) -> str:
    key = raw.strip()
    if key in _ACCOUNT_TYPE_ALIASES:
        return _ACCOUNT_TYPE_ALIASES[key]
    return key.lower()


def _parse_invoice_status(raw: str) -> InvoiceStatus:
    """Map DB status to domain enum; tolerate legacy/non-US-8 values."""
    try:
        return InvoiceStatus(raw)
    except ValueError:
        return InvoiceStatus.DRAFT


def _require_tenant(invoice: Invoice) -> uuid.UUID:
    if invoice.tenant_id is None:
        msg = "Invoice is missing a tenant id."
        raise ValueError(msg)
    return invoice.tenant_id


def _invoice_to_entity(model: InvoiceModel) -> Invoice:
    return Invoice(
        id=model.id,
        tenant_id=model.tenant_id,
        customer_id=model.customer_id,
        invoice_number=model.invoice_number or "",
        issue_date=model.issue_date,
        due_date=model.due_date,
        status=_parse_invoice_status(model.status),
        subtotal=model.subtotal if model.subtotal is not None else _ZERO,
        gst_amount=model.gst_amount if model.gst_amount is not None else _ZERO,
        total=model.total if model.total is not None else _ZERO,
        journal_entry_id=model.journal_entry_id,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
        lines=[
            InvoiceLine(
                id=line.id,
                invoice_id=line.invoice_id,
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_code_id=line.gst_code_id,
                gst_rate=line.gst_rate if line.gst_rate is not None else _ZERO,
                line_total=line.line_total if line.line_total is not None else _ZERO,
                gst_amount=line.gst_amount if line.gst_amount is not None else _ZERO,
            )
            for line in sorted(model.lines, key=lambda line_model: str(line_model.id))
        ],
    )


def _apply_lines(model: InvoiceModel, invoice: Invoice) -> None:
    model.lines = [
        InvoiceLineModel(
            id=line.id,
            invoice_id=invoice.id,
            account_id=line.account_id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            description=line.description,
            gst_code_id=line.gst_code_id,
            gst_rate=line.gst_rate,
            line_total=line.line_total,
            gst_amount=line.gst_amount,
        )
        for line in invoice.lines
    ]


def _gst_code_to_entity(model: GstCodeModel) -> GstCode:
    return GstCode(
        id=model.id,
        tenant_id=model.tenant_id,
        code=model.code,
        rate=model.rate,
        gst_kind=GstKind(model.gst_kind),
        is_active=model.is_active,
    )


def _gst_transaction_to_entity(
    model: GstTransactionModel,
) -> GstTransaction:
    if model.transaction_date is None:
        msg = f"GST transaction {model.id} has no transaction date."
        raise RuntimeError(msg)

    if model.reporting_period is None:
        msg = f"GST transaction {model.id} has no reporting period."
        raise RuntimeError(msg)

    return GstTransaction(
        id=model.id,
        tenant_id=model.tenant_id,
        source_type=GstSourceType(model.source_type),
        source_id=model.source_id,
        gst_code_id=model.gst_code_id,
        taxable_amount=model.taxable_amount,
        gst_amount=model.gst_amount,
        reporting_period=model.reporting_period,
        transaction_date=model.transaction_date,
        created_at=model.created_at,
    )


class SqlAlchemyInvoiceRepository(InvoiceRepository):
    """Invoice persistence backed by the ``invoices``/``invoice_lines`` tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice | None:
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.id == invoice_id, InvoiceModel.tenant_id == tenant_id)
            .options(selectinload(InvoiceModel.lines))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _invoice_to_entity(model) if model is not None else None

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        customer_id: uuid.UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Invoice]:
        stmt = (
            select(InvoiceModel)
            .where(InvoiceModel.tenant_id == tenant_id)
            .options(selectinload(InvoiceModel.lines))
            .order_by(InvoiceModel.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(InvoiceModel.status == status)
        if customer_id is not None:
            stmt = stmt.where(InvoiceModel.customer_id == customer_id)
        if issued_from is not None:
            stmt = stmt.where(InvoiceModel.issue_date >= issued_from)
        if issued_to is not None:
            stmt = stmt.where(InvoiceModel.issue_date <= issued_to)
        result = await self._session.execute(stmt)
        return [_invoice_to_entity(m) for m in result.scalars().unique().all()]

    async def add(self, invoice: Invoice) -> Invoice:
        model = InvoiceModel(
            id=invoice.id,
            tenant_id=invoice.tenant_id,
            customer_id=invoice.customer_id,
            invoice_number=invoice.invoice_number or "",
            amount=invoice.total,
            issue_date=invoice.issue_date,
            due_date=invoice.due_date,
            subtotal=invoice.subtotal,
            gst_amount=invoice.gst_amount,
            total=invoice.total,
            journal_entry_id=invoice.journal_entry_id,
            status=invoice.status.value,
            created_by=invoice.created_by,
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
        )
        _apply_lines(model, invoice)
        self._session.add(model)
        await self._session.flush()
        return await self._reload(_require_tenant(invoice), invoice.id)

    async def update(self, invoice: Invoice) -> Invoice:
        model = await self._session.get(InvoiceModel, invoice.id)
        if model is None:
            msg = "Invoice disappeared during update."
            raise RuntimeError(msg)

        if invoice.customer_id is not None:
            model.customer_id = invoice.customer_id
        model.invoice_number = invoice.invoice_number or ""
        model.amount = invoice.total
        model.issue_date = invoice.issue_date
        model.due_date = invoice.due_date
        model.subtotal = invoice.subtotal
        model.gst_amount = invoice.gst_amount
        model.total = invoice.total
        model.journal_entry_id = invoice.journal_entry_id
        model.status = invoice.status.value
        model.updated_at = invoice.updated_at

        await self._session.execute(
            delete(InvoiceLineModel).where(InvoiceLineModel.invoice_id == invoice.id)
        )
        for line in invoice.lines:
            self._session.add(
                InvoiceLineModel(
                    id=line.id,
                    invoice_id=invoice.id,
                    account_id=line.account_id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    description=line.description,
                    gst_code_id=line.gst_code_id,
                    gst_rate=line.gst_rate,
                    line_total=line.line_total,
                    gst_amount=line.gst_amount,
                )
            )
        await self._session.flush()
        return await self._reload(_require_tenant(invoice), invoice.id)

    async def delete(self, invoice: Invoice) -> None:
        model = await self._session.get(InvoiceModel, invoice.id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()

    async def count_with_number_prefix(self, tenant_id: uuid.UUID, prefix: str) -> int:
        stmt = (
            select(func.count())
            .select_from(InvoiceModel)
            .where(
                InvoiceModel.tenant_id == tenant_id,
                InvoiceModel.invoice_number.like(f"{prefix}%"),
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def _reload(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
        reloaded = await self.get_by_id(tenant_id, invoice_id)
        if reloaded is None:
            msg = "Invoice could not be reloaded after write."
            raise RuntimeError(msg)
        return reloaded


class SqlAlchemyCustomerRepository(CustomerRepository):
    """Customer persistence backed by the ``customers`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
        stmt = select(CustomerModel).where(
            CustomerModel.id == customer_id,
            CustomerModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Customer(
            id=model.id,
            tenant_id=model.tenant_id,
            name=model.name,
            email=model.email,
            credit_terms_days=model.credit_terms_days,
        )

    async def list_by_tenant(self, tenant_id: uuid.UUID) -> list[Customer]:
        stmt = (
            select(CustomerModel)
            .where(CustomerModel.tenant_id == tenant_id)
            .order_by(CustomerModel.name.asc())
        )
        result = await self._session.execute(stmt)
        return [
            Customer(
                id=m.id,
                tenant_id=m.tenant_id,
                name=m.name,
                email=m.email,
                credit_terms_days=m.credit_terms_days,
            )
            for m in result.scalars().all()
        ]

    async def add(self, customer: Customer) -> Customer:
        model = CustomerModel(
            id=customer.id,
            tenant_id=customer.tenant_id,
            name=customer.name,
            email=customer.email,
            credit_terms_days=customer.credit_terms_days,
        )
        self._session.add(model)
        await self._session.flush()
        return Customer(
            id=model.id,
            tenant_id=model.tenant_id,
            name=model.name,
            email=model.email,
            credit_terms_days=model.credit_terms_days,
        )


def _parse_payment_method(raw: str | None) -> PaymentMethod:
    try:
        return PaymentMethod(raw) if raw is not None else PaymentMethod.OTHER
    except ValueError:
        return PaymentMethod.OTHER


def _payment_to_entity(model: PaymentModel) -> Payment:
    return Payment(
        id=model.id,
        tenant_id=model.tenant_id,
        invoice_id=model.invoice_id,
        customer_id=model.customer_id,
        amount=model.amount if model.amount is not None else _ZERO,
        payment_date=model.payment_date,
        payment_method=_parse_payment_method(model.payment_method),
        reference=model.reference,
        deposit_account_id=model.deposit_account_id,
        journal_entry_id=model.journal_entry_id,
        idempotency_key=model.idempotency_key,
        created_by=model.created_by,
        created_at=model.created_at,
    )


class SqlAlchemyPaymentRepository(PaymentRepository):
    """Payment persistence backed by the ``payments`` table (US-9).

    Payments are immutable: this repository only supports inserts and reads.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> Payment:
        model = PaymentModel(
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
            idempotency_key=payment.idempotency_key,
            created_by=payment.created_by,
            created_at=payment.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return _payment_to_entity(model)

    async def get_by_id(self, tenant_id: uuid.UUID, payment_id: uuid.UUID) -> Payment | None:
        stmt = select(PaymentModel).where(
            PaymentModel.id == payment_id,
            PaymentModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _payment_to_entity(model) if model is not None else None

    async def list_by_invoice(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> list[Payment]:
        stmt = (
            select(PaymentModel)
            .where(
                PaymentModel.tenant_id == tenant_id,
                PaymentModel.invoice_id == invoice_id,
            )
            .order_by(PaymentModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_payment_to_entity(m) for m in result.scalars().all()]

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        invoice_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        payment_method: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Payment]:
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.tenant_id == tenant_id)
            .order_by(PaymentModel.created_at.desc())
        )
        if invoice_id is not None:
            stmt = stmt.where(PaymentModel.invoice_id == invoice_id)
        if customer_id is not None:
            stmt = stmt.where(PaymentModel.customer_id == customer_id)
        if payment_method is not None:
            stmt = stmt.where(PaymentModel.payment_method == payment_method)
        if date_from is not None:
            stmt = stmt.where(PaymentModel.payment_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(PaymentModel.payment_date <= date_to)
        result = await self._session.execute(stmt)
        return [_payment_to_entity(m) for m in result.scalars().all()]

    async def sum_paid_for_invoice(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> Decimal:
        stmt = select(func.coalesce(func.sum(PaymentModel.amount), 0)).where(
            PaymentModel.tenant_id == tenant_id,
            PaymentModel.invoice_id == invoice_id,
        )
        result = await self._session.execute(stmt)
        return Decimal(str(result.scalar_one()))

    async def get_by_idempotency_key(self, tenant_id: uuid.UUID, key: str) -> Payment | None:
        stmt = select(PaymentModel).where(
            PaymentModel.tenant_id == tenant_id,
            PaymentModel.idempotency_key == key,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _payment_to_entity(model) if model is not None else None


def _parse_credit_note_status(raw: str) -> CreditNoteStatus:
    try:
        return CreditNoteStatus(raw)
    except ValueError:
        return CreditNoteStatus.ISSUED


def _credit_note_to_entity(model: CreditNoteModel) -> CreditNote:
    return CreditNote(
        id=model.id,
        tenant_id=model.tenant_id,
        invoice_id=model.invoice_id,
        customer_id=model.customer_id,
        credit_note_number=model.credit_note_number or "",
        issue_date=model.issue_date,
        reason=model.reason,
        status=_parse_credit_note_status(model.status),
        subtotal=model.subtotal if model.subtotal is not None else _ZERO,
        gst_amount=model.gst_amount if model.gst_amount is not None else _ZERO,
        total=model.total if model.total is not None else _ZERO,
        journal_entry_id=model.journal_entry_id,
        idempotency_key=model.idempotency_key,
        created_by=model.created_by,
        created_at=model.created_at,
        lines=[
            CreditNoteLine(
                id=line.id,
                credit_note_id=line.credit_note_id,
                invoice_line_id=line.invoice_line_id,
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_code_id=line.gst_code_id,
                gst_rate=line.gst_rate if line.gst_rate is not None else _ZERO,
                line_total=line.line_total if line.line_total is not None else _ZERO,
                gst_amount=line.gst_amount if line.gst_amount is not None else _ZERO,
            )
            for line in sorted(model.lines, key=lambda line_model: str(line_model.id))
        ],
    )


class SqlAlchemyCreditNoteRepository(CreditNoteRepository):
    """Credit note persistence backed by the ``credit_notes``/``credit_note_lines`` tables (US-10).

    Credit notes are immutable: this repository only supports inserts and reads.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, credit_note: CreditNote) -> CreditNote:
        model = CreditNoteModel(
            id=credit_note.id,
            tenant_id=credit_note.tenant_id,
            invoice_id=credit_note.invoice_id,
            customer_id=credit_note.customer_id,
            credit_note_number=credit_note.credit_note_number or "",
            issue_date=credit_note.issue_date,
            reason=credit_note.reason,
            status=credit_note.status.value,
            subtotal=credit_note.subtotal,
            gst_amount=credit_note.gst_amount,
            total=credit_note.total,
            journal_entry_id=credit_note.journal_entry_id,
            idempotency_key=credit_note.idempotency_key,
            created_by=credit_note.created_by,
            created_at=credit_note.created_at,
        )
        model.lines = [
            CreditNoteLineModel(
                id=line.id,
                credit_note_id=credit_note.id,
                invoice_line_id=line.invoice_line_id,
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_code_id=line.gst_code_id,
                gst_rate=line.gst_rate,
                line_total=line.line_total,
                gst_amount=line.gst_amount,
            )
            for line in credit_note.lines
        ]
        self._session.add(model)
        await self._session.flush()
        if credit_note.tenant_id is None:
            msg = "Credit note is missing a tenant id."
            raise ValueError(msg)
        reloaded = await self.get_by_id(credit_note.tenant_id, credit_note.id)
        if reloaded is None:
            msg = "Credit note could not be reloaded after write."
            raise RuntimeError(msg)
        return reloaded

    async def get_by_id(self, tenant_id: uuid.UUID, credit_note_id: uuid.UUID) -> CreditNote | None:
        stmt = (
            select(CreditNoteModel)
            .where(
                CreditNoteModel.id == credit_note_id,
                CreditNoteModel.tenant_id == tenant_id,
            )
            .options(selectinload(CreditNoteModel.lines))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _credit_note_to_entity(model) if model is not None else None

    async def list_by_invoice(
        self, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> list[CreditNote]:
        stmt = (
            select(CreditNoteModel)
            .where(
                CreditNoteModel.tenant_id == tenant_id,
                CreditNoteModel.invoice_id == invoice_id,
            )
            .options(selectinload(CreditNoteModel.lines))
            .order_by(CreditNoteModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_credit_note_to_entity(m) for m in result.scalars().unique().all()]

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        invoice_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[CreditNote]:
        stmt = (
            select(CreditNoteModel)
            .where(CreditNoteModel.tenant_id == tenant_id)
            .options(selectinload(CreditNoteModel.lines))
            .order_by(CreditNoteModel.created_at.desc())
        )
        if invoice_id is not None:
            stmt = stmt.where(CreditNoteModel.invoice_id == invoice_id)
        if customer_id is not None:
            stmt = stmt.where(CreditNoteModel.customer_id == customer_id)
        if date_from is not None:
            stmt = stmt.where(CreditNoteModel.issue_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(CreditNoteModel.issue_date <= date_to)
        result = await self._session.execute(stmt)
        return [_credit_note_to_entity(m) for m in result.scalars().unique().all()]

    async def sum_credited_for_invoice(
        self, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(CreditNoteModel.total), 0)).where(
            CreditNoteModel.tenant_id == tenant_id,
            CreditNoteModel.invoice_id == invoice_id,
        )
        result = await self._session.execute(stmt)
        return Decimal(str(result.scalar_one()))

    async def count_with_number_prefix(self, tenant_id: uuid.UUID, prefix: str) -> int:
        stmt = (
            select(func.count())
            .select_from(CreditNoteModel)
            .where(
                CreditNoteModel.tenant_id == tenant_id,
                CreditNoteModel.credit_note_number.like(f"{prefix}%"),
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get_by_idempotency_key(self, tenant_id: uuid.UUID, key: str) -> CreditNote | None:
        stmt = (
            select(CreditNoteModel)
            .where(
                CreditNoteModel.tenant_id == tenant_id,
                CreditNoteModel.idempotency_key == key,
            )
            .options(selectinload(CreditNoteModel.lines))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _credit_note_to_entity(model) if model is not None else None


def _parse_bill_status(raw: str) -> BillStatus:
    try:
        return BillStatus(raw)
    except ValueError:
        return BillStatus.DRAFT


def _require_bill_tenant(bill: Bill) -> uuid.UUID:
    if bill.tenant_id is None:
        msg = "Bill is missing a tenant id."
        raise ValueError(msg)
    return bill.tenant_id


def _bill_to_entity(model: BillModel) -> Bill:
    return Bill(
        id=model.id,
        tenant_id=model.tenant_id,
        vendor_id=model.vendor_id,
        bill_number=model.bill_number or "",
        issue_date=model.issue_date,
        due_date=model.due_date,
        status=_parse_bill_status(model.status),
        subtotal=model.subtotal if model.subtotal is not None else _ZERO,
        gst_amount=model.gst_amount if model.gst_amount is not None else _ZERO,
        total=model.total if model.total is not None else _ZERO,
        journal_entry_id=model.journal_entry_id,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
        lines=[
            BillLine(
                id=line.id,
                bill_id=line.bill_id,
                account_id=line.account_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                description=line.description,
                gst_code_id=line.gst_code_id,
                gst_rate=line.gst_rate if line.gst_rate is not None else _ZERO,
                line_total=line.line_total if line.line_total is not None else _ZERO,
                gst_amount=line.gst_amount if line.gst_amount is not None else _ZERO,
            )
            for line in sorted(model.lines, key=lambda line_model: str(line_model.id))
        ],
    )


def _apply_bill_lines(model: BillModel, bill: Bill) -> None:
    model.lines = [
        BillLineModel(
            id=line.id,
            bill_id=bill.id,
            account_id=line.account_id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            description=line.description,
            gst_code_id=line.gst_code_id,
            gst_rate=line.gst_rate,
            line_total=line.line_total,
            gst_amount=line.gst_amount,
        )
        for line in bill.lines
    ]


class SqlAlchemyBillRepository(BillRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill | None:
        stmt = (
            select(BillModel)
            .where(BillModel.id == bill_id, BillModel.tenant_id == tenant_id)
            .options(selectinload(BillModel.lines))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _bill_to_entity(model) if model is not None else None

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        vendor_id: uuid.UUID | None = None,
        issued_from: date | None = None,
        issued_to: date | None = None,
    ) -> list[Bill]:
        stmt = (
            select(BillModel)
            .where(BillModel.tenant_id == tenant_id)
            .options(selectinload(BillModel.lines))
            .order_by(BillModel.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(BillModel.status == status)
        if vendor_id is not None:
            stmt = stmt.where(BillModel.vendor_id == vendor_id)
        if issued_from is not None:
            stmt = stmt.where(BillModel.issue_date >= issued_from)
        if issued_to is not None:
            stmt = stmt.where(BillModel.issue_date <= issued_to)
        result = await self._session.execute(stmt)
        return [_bill_to_entity(m) for m in result.scalars().unique().all()]

    async def add(self, bill: Bill) -> Bill:
        model = BillModel(
            id=bill.id,
            tenant_id=bill.tenant_id,
            vendor_id=bill.vendor_id,
            bill_number=bill.bill_number or "",
            issue_date=bill.issue_date,
            due_date=bill.due_date,
            subtotal=bill.subtotal,
            gst_amount=bill.gst_amount,
            total=bill.total,
            journal_entry_id=bill.journal_entry_id,
            status=bill.status.value,
            created_by=bill.created_by,
            created_at=bill.created_at,
            updated_at=bill.updated_at,
        )
        _apply_bill_lines(model, bill)
        self._session.add(model)
        await self._session.flush()
        return await self._reload(_require_bill_tenant(bill), bill.id)

    async def update(self, bill: Bill) -> Bill:
        model = await self._session.get(BillModel, bill.id)
        if model is None:
            msg = "Bill disappeared during update."
            raise RuntimeError(msg)
        if bill.vendor_id is not None:
            model.vendor_id = bill.vendor_id
        model.bill_number = bill.bill_number or ""
        model.issue_date = bill.issue_date
        model.due_date = bill.due_date
        model.subtotal = bill.subtotal
        model.gst_amount = bill.gst_amount
        model.total = bill.total
        model.journal_entry_id = bill.journal_entry_id
        model.status = bill.status.value
        model.updated_at = bill.updated_at
        await self._session.execute(delete(BillLineModel).where(BillLineModel.bill_id == bill.id))
        for line in bill.lines:
            self._session.add(
                BillLineModel(
                    id=line.id,
                    bill_id=bill.id,
                    account_id=line.account_id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    description=line.description,
                    gst_code_id=line.gst_code_id,
                    gst_rate=line.gst_rate,
                    line_total=line.line_total,
                    gst_amount=line.gst_amount,
                )
            )
        await self._session.flush()
        return await self._reload(_require_bill_tenant(bill), bill.id)

    async def delete(self, bill: Bill) -> None:
        model = await self._session.get(BillModel, bill.id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()

    async def count_with_number_prefix(self, tenant_id: uuid.UUID, prefix: str) -> int:
        stmt = (
            select(func.count())
            .select_from(BillModel)
            .where(
                BillModel.tenant_id == tenant_id,
                BillModel.bill_number.like(f"{prefix}%"),
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def _reload(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Bill:
        reloaded = await self.get_by_id(tenant_id, bill_id)
        if reloaded is None:
            msg = "Bill could not be reloaded after write."
            raise RuntimeError(msg)
        return reloaded


class SqlAlchemyVendorRepository(VendorRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID, vendor_id: uuid.UUID) -> Vendor | None:
        stmt = select(VendorModel).where(
            VendorModel.id == vendor_id,
            VendorModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Vendor(
            id=model.id,
            tenant_id=model.tenant_id,
            name=model.name,
            email=model.email,
        )

    async def list_by_tenant(self, tenant_id: uuid.UUID) -> list[Vendor]:
        stmt = (
            select(VendorModel)
            .where(VendorModel.tenant_id == tenant_id)
            .order_by(VendorModel.name.asc())
        )
        result = await self._session.execute(stmt)
        return [
            Vendor(id=m.id, tenant_id=m.tenant_id, name=m.name, email=m.email)
            for m in result.scalars().all()
        ]

    async def add(self, vendor: Vendor) -> Vendor:
        model = VendorModel(
            id=vendor.id,
            tenant_id=vendor.tenant_id,
            name=vendor.name,
            email=vendor.email,
        )
        self._session.add(model)
        await self._session.flush()
        return Vendor(
            id=model.id,
            tenant_id=model.tenant_id,
            name=model.name,
            email=model.email,
        )


def _bill_payment_to_entity(model: BillPaymentModel) -> BillPayment:
    return BillPayment(
        id=model.id,
        tenant_id=model.tenant_id,
        bill_id=model.bill_id,
        vendor_id=model.vendor_id,
        amount=model.amount if model.amount is not None else _ZERO,
        payment_date=model.payment_date,
        payment_method=_parse_payment_method(model.payment_method),
        reference=model.reference,
        payment_account_id=model.payment_account_id,
        journal_entry_id=model.journal_entry_id,
        idempotency_key=model.idempotency_key,
        created_by=model.created_by,
        created_at=model.created_at,
    )


class SqlAlchemyBillPaymentRepository(BillPaymentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: BillPayment) -> BillPayment:
        model = BillPaymentModel(
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
            idempotency_key=payment.idempotency_key,
            created_by=payment.created_by,
            created_at=payment.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return _bill_payment_to_entity(model)

    async def get_by_id(self, tenant_id: uuid.UUID, payment_id: uuid.UUID) -> BillPayment | None:
        stmt = select(BillPaymentModel).where(
            BillPaymentModel.id == payment_id,
            BillPaymentModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _bill_payment_to_entity(model) if model is not None else None

    async def list_by_bill(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> list[BillPayment]:
        stmt = (
            select(BillPaymentModel)
            .where(
                BillPaymentModel.tenant_id == tenant_id,
                BillPaymentModel.bill_id == bill_id,
            )
            .order_by(BillPaymentModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [_bill_payment_to_entity(m) for m in result.scalars().all()]

    async def list_by_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        bill_id: uuid.UUID | None = None,
        vendor_id: uuid.UUID | None = None,
        payment_method: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[BillPayment]:
        stmt = (
            select(BillPaymentModel)
            .where(BillPaymentModel.tenant_id == tenant_id)
            .order_by(BillPaymentModel.created_at.desc())
        )
        if bill_id is not None:
            stmt = stmt.where(BillPaymentModel.bill_id == bill_id)
        if vendor_id is not None:
            stmt = stmt.where(BillPaymentModel.vendor_id == vendor_id)
        if payment_method is not None:
            stmt = stmt.where(BillPaymentModel.payment_method == payment_method)
        if date_from is not None:
            stmt = stmt.where(BillPaymentModel.payment_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(BillPaymentModel.payment_date <= date_to)
        result = await self._session.execute(stmt)
        return [_bill_payment_to_entity(m) for m in result.scalars().all()]

    async def sum_paid_for_bill(self, tenant_id: uuid.UUID, bill_id: uuid.UUID) -> Decimal:
        stmt = select(func.coalesce(func.sum(BillPaymentModel.amount), 0)).where(
            BillPaymentModel.tenant_id == tenant_id,
            BillPaymentModel.bill_id == bill_id,
        )
        result = await self._session.execute(stmt)
        return Decimal(str(result.scalar_one()))

    async def get_by_idempotency_key(self, tenant_id: uuid.UUID, key: str) -> BillPayment | None:
        stmt = select(BillPaymentModel).where(
            BillPaymentModel.tenant_id == tenant_id,
            BillPaymentModel.idempotency_key == key,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _bill_payment_to_entity(model) if model is not None else None


class SqlAlchemyGstRepository(GstRepository):
    """GST code and reporting transaction persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_code_by_id(
        self,
        tenant_id: uuid.UUID,
        gst_code_id: uuid.UUID,
    ) -> GstCode | None:
        stmt = select(GstCodeModel).where(
            GstCodeModel.id == gst_code_id,
            GstCodeModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _gst_code_to_entity(model) if model is not None else None

    async def list_codes(
        self,
        tenant_id: uuid.UUID,
        *,
        active_only: bool = True,
    ) -> list[GstCode]:
        stmt = (
            select(GstCodeModel)
            .where(GstCodeModel.tenant_id == tenant_id)
            .order_by(GstCodeModel.code.asc())
        )

        if active_only:
            stmt = stmt.where(GstCodeModel.is_active.is_(True))

        result = await self._session.execute(stmt)
        return [_gst_code_to_entity(model) for model in result.scalars().all()]

    async def add_codes(
        self,
        codes: Sequence[GstCode],
    ) -> list[GstCode]:
        """Persist tenant-scoped GST codes."""
        if not codes:
            return []

        models = [
            GstCodeModel(
                id=code.id,
                tenant_id=code.tenant_id,
                code=code.code,
                rate=code.rate,
                gst_kind=code.gst_kind.value,
                is_active=code.is_active,
            )
            for code in codes
        ]

        self._session.add_all(models)
        await self._session.flush()

        return list(codes)

    async def add_transactions(
        self,
        transactions: Sequence[GstTransaction],
    ) -> list[GstTransaction]:
        if not transactions:
            return []

        models = [
            GstTransactionModel(
                id=transaction.id,
                tenant_id=transaction.tenant_id,
                source_type=transaction.source_type.value,
                source_id=transaction.source_id,
                gst_code_id=transaction.gst_code_id,
                taxable_amount=transaction.taxable_amount,
                gst_amount=transaction.gst_amount,
                reporting_period=transaction.reporting_period,
                transaction_date=transaction.transaction_date,
                created_at=transaction.created_at,
            )
            for transaction in transactions
        ]

        self._session.add_all(models)
        await self._session.flush()

        return transactions

    async def list_transactions_by_period(
        self,
        tenant_id: uuid.UUID,
        reporting_period: str,
    ) -> list[GstTransaction]:
        stmt = (
            select(GstTransactionModel)
            .where(
                GstTransactionModel.tenant_id == tenant_id,
                GstTransactionModel.reporting_period == reporting_period,
            )
            .order_by(
                GstTransactionModel.transaction_date.asc(),
                GstTransactionModel.created_at.asc(),
                GstTransactionModel.id.asc(),
            )
        )

        result = await self._session.execute(stmt)
        return [
            _gst_transaction_to_entity(model)
            for model in result.scalars().all()
        ]


class SqlAccountReader(AccountReader):
    """Reads the shared ``chart_of_accounts`` table without importing coa models."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: uuid.UUID, account_id: uuid.UUID) -> AccountInfo | None:
        stmt = text(
            "SELECT id, code, name, type, is_active FROM chart_of_accounts "
            "WHERE id = :account_id AND tenant_id = :tenant_id"
        )
        result = await self._session.execute(
            stmt, {"account_id": str(account_id), "tenant_id": str(tenant_id)}
        )
        return self._row_to_account(result.mappings().first())

    async def get_by_code(self, tenant_id: uuid.UUID, code: str) -> AccountInfo | None:
        stmt = text(
            "SELECT id, code, name, type, is_active FROM chart_of_accounts "
            "WHERE code = :code AND tenant_id = :tenant_id"
        )
        result = await self._session.execute(stmt, {"code": code, "tenant_id": str(tenant_id)})
        return self._row_to_account(result.mappings().first())

    @staticmethod
    def _row_to_account(row: RowMapping | None) -> AccountInfo | None:
        if row is None:
            return None
        return AccountInfo(
            id=uuid.UUID(str(row["id"])),
            code=str(row["code"]),
            name=str(row["name"]),
            account_type=_normalize_account_type(str(row["type"])),
            is_active=bool(row["is_active"]),
        )


class SqlLedgerPoster(LedgerPoster):
    """Posts journal entries into the shared ledger tables via SQL.

    Mirrors ledger-service's ``journal_entries``/``journal_entry_lines`` schema so
    entries posted here are indistinguishable from ones the ledger writes itself.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_period_closed(self, tenant_id: uuid.UUID, on_date: date) -> bool:
        stmt = text(
            "SELECT 1 FROM accounting_periods "
            "WHERE tenant_id = :tenant_id AND start_date <= :on_date "
            "AND end_date >= :on_date AND is_closed = :closed LIMIT 1"
        )
        result = await self._session.execute(
            stmt,
            {"tenant_id": str(tenant_id), "on_date": on_date, "closed": True},
        )
        return result.first() is not None

    async def post_journal_entry(
        self,
        *,
        tenant_id: uuid.UUID,
        entry_date: date,
        reference: str,
        description: str,
        source_id: str,
        created_by: uuid.UUID | None,
        lines: Sequence[JournalLineInput],
        source_type: str = "invoice",
        is_reversal: bool = False,
        reversed_entry_id: str | None = None,
    ) -> str:
        from accounting_shared.exceptions import ConflictError, ValidationError

        if len(lines) < 2:
            raise ValidationError("A journal entry must have at least two lines.")

        total_debit = sum((line.debit_amount for line in lines), _ZERO)
        total_credit = sum((line.credit_amount for line in lines), _ZERO)
        if total_debit != total_credit:
            raise ValidationError(
                f"Journal entry is not balanced: debit {total_debit}, credit {total_credit}."
            )

        if await self.is_period_closed(tenant_id, entry_date):
            raise ConflictError(
                f"Cannot post journal entry: {entry_date} is in a closed accounting period."
            )

        entry_id = str(uuid.uuid4())
        await self._session.execute(
            text(
                "INSERT INTO journal_entries "
                "(id, tenant_id, entry_date, reference, description, source_type, "
                "source_id, created_by, is_reversal, reversed_entry_id, created_at) "
                "VALUES (:id, :tenant_id, :entry_date, :reference, :description, :source_type, "
                ":source_id, :created_by, :is_reversal, :reversed_entry_id, :created_at)"
            ),
            {
                "id": entry_id,
                "tenant_id": str(tenant_id),
                "entry_date": entry_date,
                "reference": reference,
                "description": description,
                "source_type": source_type,
                "source_id": source_id,
                "created_by": str(created_by) if created_by is not None else None,
                "is_reversal": is_reversal,
                "reversed_entry_id": reversed_entry_id,
                "created_at": datetime.utcnow(),
            },
        )
        for line in lines:
            await self._session.execute(
                text(
                    "INSERT INTO journal_entry_lines "
                    "(id, tenant_id, journal_entry_id, account_id, debit_amount, "
                    "credit_amount, description) "
                    "VALUES (:id, :tenant_id, :journal_entry_id, :account_id, "
                    ":debit_amount, :credit_amount, :description)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_id),
                    "journal_entry_id": entry_id,
                    "account_id": line.account_id,
                    "debit_amount": line.debit_amount,
                    "credit_amount": line.credit_amount,
                    "description": line.description,
                },
            )
        await self._session.flush()
        return entry_id
