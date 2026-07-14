"""US-11/US-12: Add bill_payments table + bill_line columns + bill created_by/updated_at.

This adds the infrastructure needed for the Bills API (vendor bills and payments).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_007_bill_payments"
down_revision = "ar_ap_006_bank_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bills", sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("bills", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.add_column("bill_lines", sa.Column("quantity", sa.Numeric(18, 2), nullable=False, server_default=sa.text("1")))
    op.add_column("bill_lines", sa.Column("unit_price", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")))
    op.add_column("bill_lines", sa.Column("line_total", sa.Numeric(18, 2), nullable=True))
    op.add_column("bill_lines", sa.Column("gst_amount", sa.Numeric(18, 2), nullable=True))
    op.alter_column("bills", "bill_number", server_default=sa.text("''"))
    op.alter_column("bills", "status", server_default=sa.text("'draft'"))

    op.create_table(
        "bill_payments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("bill_id", sa.Uuid(as_uuid=True), sa.ForeignKey("bills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", sa.Uuid(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("payment_method", sa.String(32), nullable=False, server_default=sa.text("'bank_transfer'")),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("payment_account_id", sa.Uuid(as_uuid=True), sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("journal_entry_id", sa.String(36), sa.ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_bill_payments_tenant_idempotency_key"),
    )
    op.create_index("ix_bill_payments_tenant_id", "bill_payments", ["tenant_id"])
    op.create_index("ix_bill_payments_bill_id", "bill_payments", ["bill_id"])


def downgrade() -> None:
    op.drop_table("bill_payments")
    op.drop_column("bill_lines", "gst_amount")
    op.drop_column("bill_lines", "line_total")
    op.drop_column("bill_lines", "unit_price")
    op.drop_column("bill_lines", "quantity")
    op.drop_column("bills", "updated_at")
    op.drop_column("bills", "created_by")
