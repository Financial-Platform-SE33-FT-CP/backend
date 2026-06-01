"""US-8: unique invoice numbers per tenant (non-empty numbers only).

Draft invoices keep an empty invoice_number; issued numbers must be unique
within a tenant to prevent duplicate sequencing under concurrency.
"""

from __future__ import annotations

from alembic import op

revision = "ar_ap_003_invoice_number_unique"
down_revision = "ar_ap_002_invoice_us8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_tenant_number "
        "ON invoices (tenant_id, invoice_number) "
        "WHERE invoice_number <> ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_invoices_tenant_number")
