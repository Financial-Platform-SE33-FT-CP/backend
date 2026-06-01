"""US-10: issue credit notes against issued invoices.

Adds the ``credit_notes`` and ``credit_note_lines`` tables. A credit note is an
immutable financial record linked to the invoice it corrects and to the balanced
reversal journal entry it posts (Debit Revenue, Debit GST Output, Credit Accounts
Receivable). An idempotency key (unique per tenant) makes retries safe.

Prerequisite migrations on the same database: tenant (tenants), coa
(chart_of_accounts), ledger (journal_entries), and ar_ap_004_payment_us9.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_005_credit_note_us10"
down_revision = "ar_ap_004_payment_us9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_notes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invoice_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("customer_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("credit_note_number", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="issued"),
        sa.Column(
            "subtotal", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"
        ),
        sa.Column(
            "gst_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"
        ),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_credit_notes_tenant_id", "credit_notes", ["tenant_id"], unique=False)
    op.create_index("ix_credit_notes_invoice_id", "credit_notes", ["invoice_id"], unique=False)
    # Idempotency keys are unique per tenant when present; NULL keys are unconstrained.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_notes_tenant_idempotency_key "
        "ON credit_notes (tenant_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    # Credit note numbers are unique per tenant when assigned (non-empty).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_notes_tenant_number "
        "ON credit_notes (tenant_id, credit_note_number) "
        "WHERE credit_note_number <> ''"
    )

    op.create_table(
        "credit_note_lines",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("credit_note_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invoice_line_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "quantity", sa.Numeric(precision=18, scale=4), nullable=False, server_default="1"
        ),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gst_rate", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "gst_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"
        ),
        sa.ForeignKeyConstraint(["credit_note_id"], ["credit_notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_line_id"], ["invoice_lines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["chart_of_accounts.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_credit_note_lines_credit_note_id",
        "credit_note_lines",
        ["credit_note_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_credit_note_lines_credit_note_id", table_name="credit_note_lines")
    op.drop_table("credit_note_lines")
    op.execute("DROP INDEX IF EXISTS uq_credit_notes_tenant_number")
    op.execute("DROP INDEX IF EXISTS uq_credit_notes_tenant_idempotency_key")
    op.drop_index("ix_credit_notes_invoice_id", table_name="credit_notes")
    op.drop_index("ix_credit_notes_tenant_id", table_name="credit_notes")
    op.drop_table("credit_notes")
