"""AR/AP SQLAlchemy models."""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class InvoiceModel(Base):
    """SQLAlchemy model for the invoices table."""

    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    invoice_number = Column(String(100), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    due_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    payments = relationship("PaymentModel", back_populates="invoice")


class PaymentModel(Base):
    """SQLAlchemy model for the payments table."""

    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    payment_date = Column(Date, nullable=True)

    invoice = relationship("InvoiceModel", back_populates="payments")
