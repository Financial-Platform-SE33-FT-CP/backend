"""Ledger journal, lines, accounting periods, monthly balances, outbox."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ledger_001_journal_control"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("is_reversal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reversed_entry_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reversed_entry_id"],
            ["journal_entries.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_journal_entries_tenant_entry_date",
        "journal_entries",
        ["tenant_id", "entry_date"],
        unique=False,
    )
    op.create_index(
        "ix_journal_entries_tenant_id",
        "journal_entries",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "journal_entry_lines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("debit_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("credit_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "debit_amount = 0 OR credit_amount = 0",
            name="ck_journal_entry_lines_debit_or_credit_zero",
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"],
            ["journal_entries.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_journal_entry_lines_journal_entry_id",
        "journal_entry_lines",
        ["journal_entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_entry_lines_tenant_id",
        "journal_entry_lines",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_entry_lines_account_id",
        "journal_entry_lines",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_entry_lines_tenant_account",
        "journal_entry_lines",
        ["tenant_id", "account_id"],
        unique=False,
    )

    op.create_table(
        "accounting_periods",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("closed_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "start_date",
            "end_date",
            name="uq_accounting_periods_tenant_range",
        ),
    )
    op.create_index(
        "ix_accounting_periods_tenant_id",
        "accounting_periods",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "monthly_account_balances",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column(
            "debit_total",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "credit_total",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["chart_of_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "account_id",
            "year",
            "month",
            name="uq_monthly_account_balances_tenant_account_period",
        ),
    )
    op.create_index(
        "ix_monthly_account_balances_tenant_id",
        "monthly_account_balances",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_monthly_account_balances_account_id",
        "monthly_account_balances",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_outbox_events_event_type",
        "outbox_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_events_tenant_id",
        "outbox_events",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_tenant_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_monthly_account_balances_account_id", table_name="monthly_account_balances")
    op.drop_index("ix_monthly_account_balances_tenant_id", table_name="monthly_account_balances")
    op.drop_table("monthly_account_balances")
    op.drop_index("ix_accounting_periods_tenant_id", table_name="accounting_periods")
    op.drop_table("accounting_periods")
    op.drop_index("ix_journal_entry_lines_tenant_account", table_name="journal_entry_lines")
    op.drop_index("ix_journal_entry_lines_account_id", table_name="journal_entry_lines")
    op.drop_index("ix_journal_entry_lines_tenant_id", table_name="journal_entry_lines")
    op.drop_index("ix_journal_entry_lines_journal_entry_id", table_name="journal_entry_lines")
    op.drop_table("journal_entry_lines")
    op.drop_index("ix_journal_entries_tenant_id", table_name="journal_entries")
    op.drop_index("ix_journal_entries_tenant_entry_date", table_name="journal_entries")
    op.drop_table("journal_entries")
