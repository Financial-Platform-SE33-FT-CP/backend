import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.schema import CheckConstraint, Index, UniqueConstraint


class Base(DeclarativeBase):
    pass


class JournalEntryModel(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (Index("ix_journal_entries_tenant_entry_date", "tenant_id", "entry_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_reversal: Mapped[bool] = mapped_column(default=False, nullable=False)
    reversed_entry_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    lines: Mapped[list["JournalEntryLineModel"]] = relationship(
        "JournalEntryLineModel",
        back_populates="journal_entry",
        cascade="all, delete-orphan",
    )


class JournalEntryLineModel(Base):
    __tablename__ = "journal_entry_lines"
    __table_args__ = (
        CheckConstraint(
            "debit_amount = 0 OR credit_amount = 0",
            name="ck_journal_entry_lines_debit_or_credit_zero",
        ),
        Index("ix_journal_entry_lines_tenant_account", "tenant_id", "account_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    journal_entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    journal_entry: Mapped["JournalEntryModel"] = relationship(
        "JournalEntryModel",
        back_populates="lines",
    )


class AccountingPeriodModel(Base):
    """Fiscal period with optional close lock (proposal accounting_periods)."""

    __tablename__ = "accounting_periods"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "start_date",
            "end_date",
            name="uq_accounting_periods_tenant_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_closed: Mapped[bool] = mapped_column(default=False, nullable=False)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MonthlyAccountBalanceModel(Base):
    """Optional rollup for reporting performance (proposal monthly_account_balances)."""

    __tablename__ = "monthly_account_balances"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "account_id",
            "year",
            "month",
            name="uq_monthly_account_balances_tenant_account_period",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    debit_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    credit_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEventModel(Base):
    """Transactional outbox for async consumers (proposal outbox_events)."""

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
