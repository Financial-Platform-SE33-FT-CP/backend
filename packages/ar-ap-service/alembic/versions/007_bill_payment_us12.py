"""US-12: pay vendor bills.

Adds the ``bill_payments`` table. A bill payment is an immutable financial record
linked to the bill it settles and to the balanced journal entry it posts
(Debit Accounts Payable, Credit Bank/Cash). An idempotency key (unique per
tenant) makes retries safe.

Prerequisite migrations on the same database: tenant (tenants), coa
(chart_of_accounts), ledger (journal_entries), and ar_ap_006_bill_us11.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_007_bill_payment_us12"
down_revision = "ar_ap_006_bill_us11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bill_payments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("bill_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("vendor_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column(
            "payment_method",
            sa.String(length=32),
            nullable=False,
            server_default="bank_transfer",
        ),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("payment_account_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["bill_id"], ["bills.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["payment_account_id"], ["chart_of_accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_bill_payments_bill_id", "bill_payments", ["bill_id"], unique=False)
    op.create_index("ix_bill_payments_tenant_id", "bill_payments", ["tenant_id"], unique=False)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bill_payments_tenant_idempotency_key "
        "ON bill_payments (tenant_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bill_payments_tenant_idempotency_key")
    op.drop_index("ix_bill_payments_tenant_id", table_name="bill_payments")
    op.drop_index("ix_bill_payments_bill_id", table_name="bill_payments")
    op.drop_table("bill_payments")
