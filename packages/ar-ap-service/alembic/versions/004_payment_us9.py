"""US-9: record customer payments against invoices.

Extends the minimal ``payments`` table from ar_ap_001 with the columns needed to
record a customer payment and tie it to its balanced journal entry: customer,
method, reference, deposit (bank/cash) account, journal_entry_id, audit columns
and an idempotency key (unique per tenant) to make retries safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_004_payment_us9"
down_revision = "ar_ap_003_invoice_number_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("customer_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column(
        "payments",
        sa.Column(
            "payment_method",
            sa.String(length=32),
            nullable=False,
            server_default="bank_transfer",
        ),
    )
    op.add_column("payments", sa.Column("reference", sa.String(length=255), nullable=True))
    op.add_column(
        "payments", sa.Column("deposit_account_id", sa.Uuid(as_uuid=True), nullable=True)
    )
    op.add_column(
        "payments", sa.Column("journal_entry_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "payments", sa.Column("idempotency_key", sa.String(length=255), nullable=True)
    )
    op.add_column("payments", sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column(
        "payments",
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"], unique=False)
    op.create_foreign_key(
        "fk_payments_customer_id",
        "payments",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_payments_journal_entry_id",
        "payments",
        "journal_entries",
        ["journal_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Idempotency keys are unique per tenant when present; NULL keys are unconstrained.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_tenant_idempotency_key "
        "ON payments (tenant_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_payments_tenant_idempotency_key")
    op.drop_constraint("fk_payments_journal_entry_id", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_deposit_account_id", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_customer_id", "payments", type_="foreignkey")
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_column("payments", "created_at")
    op.drop_column("payments", "created_by")
    op.drop_column("payments", "idempotency_key")
    op.drop_column("payments", "journal_entry_id")
    op.drop_column("payments", "deposit_account_id")
    op.drop_column("payments", "reference")
    op.drop_column("payments", "payment_method")
    op.drop_column("payments", "customer_id")
