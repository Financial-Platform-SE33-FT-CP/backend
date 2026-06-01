"""AR/AP SQLAlchemy models (proposal-aligned domain + existing invoice amount field)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship
from sqlalchemy.schema import UniqueConstraint

Base = declarative_base()


class CustomerModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    credit_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class VendorModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "vendors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    email = Column(String(254), nullable=True)


class GstCodeModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "gst_codes"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_gst_codes_tenant_code"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code = Column(String(32), nullable=False)
    rate = Column(Numeric(8, 4), nullable=False)
    gst_kind = Column(String(16), nullable=False)


class InvoiceModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    gst_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    journal_entry_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lines: Mapped[list["InvoiceLineModel"]] = relationship(
        "InvoiceLineModel",
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["PaymentModel"]] = relationship("PaymentModel", back_populates="invoice")


class InvoiceLineModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gst_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )

    invoice: Mapped["InvoiceModel"] = relationship("InvoiceModel", back_populates="lines")


class BillModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "bills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vendor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    bill_number = Column(String(100), nullable=False)
    issue_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(32), nullable=False, default="unpaid")
    subtotal = Column(Numeric(18, 2), nullable=True)
    gst_amount = Column(Numeric(18, 2), nullable=True)
    total = Column(Numeric(18, 2), nullable=True)
    journal_entry_id = Column(
        String(36),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BillLineModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "bill_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    bill_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description = Column(Text, nullable=True)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount = Column(Numeric(18, 2), nullable=False)
    gst_rate = Column(Numeric(8, 4), nullable=True)


class BankAccountModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "bank_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    account_number = Column(String(64), nullable=True)
    currency = Column(String(3), nullable=False, default="SGD")
    opening_balance = Column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))


class BankTransactionModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "bank_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bank_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bank_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transaction_date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    amount = Column(Numeric(18, 2), nullable=False)
    matched = Column(Boolean, nullable=False, default=False)
    journal_entry_id = Column(
        String(36),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )


class GstTransactionModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "gst_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(String(16), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    gst_code_id = Column(
        UUID(as_uuid=True),
        ForeignKey("gst_codes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    taxable_amount = Column(Numeric(18, 2), nullable=False)
    gst_amount = Column(Numeric(18, 2), nullable=False)
    reporting_period = Column(String(32), nullable=True)


class PaymentModel(Base):  # type: ignore[misc, valid-type]
    """SQLAlchemy model for the payments table (US-9: record customer payments)."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_payments_tenant_idempotency_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False, default="bank_transfer")
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deposit_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    journal_entry_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    invoice: Mapped["InvoiceModel"] = relationship("InvoiceModel", back_populates="payments")


class CreditNoteModel(Base):  # type: ignore[misc, valid-type]
    """SQLAlchemy model for the credit_notes table (US-10: issue credit notes).

    A credit note is an immutable financial record linked to the issued invoice
    it corrects. It always carries the id of its balanced reversal journal entry.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_credit_notes_tenant_idempotency_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=True,
    )
    credit_note_number: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="issued")
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )
    gst_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    journal_entry_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    lines: Mapped[list["CreditNoteLineModel"]] = relationship(
        "CreditNoteLineModel",
        back_populates="credit_note",
        cascade="all, delete-orphan",
    )


class CreditNoteLineModel(Base):  # type: ignore[misc, valid-type]
    __tablename__ = "credit_note_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    credit_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credit_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoice_lines.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gst_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )

    credit_note: Mapped["CreditNoteModel"] = relationship(
        "CreditNoteModel", back_populates="lines"
    )
