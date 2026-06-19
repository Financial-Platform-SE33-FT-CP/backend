"""US-11: record vendor bills (align bills/bill_lines with invoice structure).

Extends the scaffold ``bills``/``bill_lines`` tables from ar_ap_001 with draft
workflow fields, invoice-style line columns (quantity, unit_price, line_total,
gst_amount), audit columns and a partial unique index on bill numbers per tenant.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_006_bill_us11"
down_revision = "ar_ap_005_credit_note_us10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE bills SET status = 'draft' WHERE status = 'unpaid'")
    op.alter_column(
        "bills",
        "status",
        server_default="draft",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "bills",
        "bill_number",
        server_default="",
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )
    op.add_column("bills", sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("bills", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.add_column(
        "bill_lines",
        sa.Column(
            "quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "bill_lines",
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=True),
    )
    op.add_column(
        "bill_lines",
        sa.Column("line_total", sa.Numeric(precision=18, scale=2), nullable=True),
    )
    op.add_column(
        "bill_lines",
        sa.Column(
            "gst_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    # Migrate legacy ``amount`` column into quantity/unit_price/line_total.
    op.execute(
        "UPDATE bill_lines SET unit_price = amount, line_total = amount "
        "WHERE unit_price IS NULL"
    )
    op.alter_column(
        "bill_lines",
        "unit_price",
        existing_type=sa.Numeric(precision=18, scale=2),
        nullable=False,
    )
    op.alter_column(
        "bill_lines",
        "line_total",
        existing_type=sa.Numeric(precision=18, scale=2),
        nullable=False,
    )
    op.drop_column("bill_lines", "amount")

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bills_tenant_bill_number "
        "ON bills (tenant_id, bill_number) "
        "WHERE bill_number <> ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bills_tenant_bill_number")
    op.add_column(
        "bill_lines",
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
    )
    op.execute("UPDATE bill_lines SET amount = line_total")
    op.alter_column(
        "bill_lines",
        "amount",
        existing_type=sa.Numeric(precision=18, scale=2),
        nullable=False,
    )
    op.drop_column("bill_lines", "gst_amount")
    op.drop_column("bill_lines", "line_total")
    op.drop_column("bill_lines", "unit_price")
    op.drop_column("bill_lines", "quantity")
    op.drop_column("bills", "updated_at")
    op.drop_column("bills", "created_by")
    op.alter_column(
        "bills",
        "bill_number",
        server_default=None,
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )
    op.alter_column(
        "bills",
        "status",
        server_default="unpaid",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
