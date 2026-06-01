"""US-8: invoice issuing support columns (created_by, updated_at, line gst_amount).

Adds audit/ownership columns to invoices and a per-line GST amount so issuing an
invoice can persist computed tax without recomputation.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_002_invoice_us8"
down_revision = "ar_ap_001_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "invoice_lines",
        sa.Column(
            "gst_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("invoice_lines", "gst_amount")
    op.drop_column("invoices", "updated_at")
    op.drop_column("invoices", "created_by")
