import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JournalEntryModel(Base):
    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    lines = relationship("JournalEntryLineModel", back_populates="journal_entry", cascade="all, delete-orphan")


class JournalEntryLineModel(Base):
    __tablename__ = "journal_entry_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    journal_entry_id: Mapped[str] = mapped_column(String(36), ForeignKey("journal_entries.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    journal_entry = relationship("JournalEntryModel", back_populates="lines")
