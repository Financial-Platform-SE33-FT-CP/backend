"""AR/AP SQLAlchemy models (proposal-aligned domain + existing invoice amount field)."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.schema import UniqueConstraint

Base = declarative_base()


class CustomerModel(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    email = Column(String(254), nullable=True)
    credit_terms_days = Column(Integer, nullable=True)


class VendorModel(Base):
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


class GstCodeModel(Base):
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


class InvoiceModel(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invoice_number = Column(String(100), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    issue_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    subtotal = Column(Numeric(18, 2), nullable=True)
    gst_amount = Column(Numeric(18, 2), nullable=True)
    total = Column(Numeric(18, 2), nullable=True)
    journal_entry_id = Column(
        String(36),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(50), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    payments = relationship("PaymentModel", back_populates="invoice")


class InvoiceLineModel(Base):
    __tablename__ = "invoice_lines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id = Column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description = Column(Text, nullable=True)
    quantity = Column(Numeric(18, 4), nullable=False, default=1)
    unit_price = Column(Numeric(18, 2), nullable=False)
    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    gst_rate = Column(Numeric(8, 4), nullable=True)
    line_total = Column(Numeric(18, 2), nullable=False)


class BillModel(Base):
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


class BillLineModel(Base):
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


class BankAccountModel(Base):
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


class BankTransactionModel(Base):
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


class GstTransactionModel(Base):
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


class PaymentModel(Base):
    """SQLAlchemy model for the payments table."""

    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    payment_date = Column(Date, nullable=True)

    invoice = relationship("InvoiceModel", back_populates="payments")
