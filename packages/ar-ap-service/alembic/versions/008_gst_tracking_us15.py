"""US-15: track GST for invoices, bills, and credit notes.

Links invoice, bill, and credit-note lines to tenant-scoped GST codes and
enhances ``gst_transactions`` with transaction dates and audit timestamps.

Each posted financial document may produce one GST transaction per GST code.
A unique index on tenant, source type, source ID, and GST code prevents request
retries from recording duplicate GST transactions.

The GST code foreign keys are initially nullable to preserve compatibility with
financial records created before US-15. New transactions should always provide
a GST code through application-level validation.

Prerequisite migrations on the same database: tenant (tenants), coa
(chart_of_accounts), ledger (journal_entries), and
ar_ap_007_bill_payment_us12.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_008_gst_tracking_us15"
down_revision = "ar_ap_007_bill_payment_us12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GST codes may be deactivated instead of deleted, preserving references
    # from historical financial and GST transactions.
    op.add_column(
        "gst_codes",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # Link invoice lines to their selected GST code.
    op.add_column(
        "invoice_lines",
        sa.Column(
            "gst_code_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_invoice_lines_gst_code_id",
        "invoice_lines",
        "gst_codes",
        ["gst_code_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_invoice_lines_gst_code_id",
        "invoice_lines",
        ["gst_code_id"],
        unique=False,
    )

    # Link vendor bill lines to their selected GST code.
    op.add_column(
        "bill_lines",
        sa.Column(
            "gst_code_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_bill_lines_gst_code_id",
        "bill_lines",
        "gst_codes",
        ["gst_code_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_bill_lines_gst_code_id",
        "bill_lines",
        ["gst_code_id"],
        unique=False,
    )

    # Credit notes retain the GST code of the tax being reversed.
    op.add_column(
        "credit_note_lines",
        sa.Column(
            "gst_code_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_credit_note_lines_gst_code_id",
        "credit_note_lines",
        "gst_codes",
        ["gst_code_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_credit_note_lines_gst_code_id",
        "credit_note_lines",
        ["gst_code_id"],
        unique=False,
    )

    # Store the accounting date used to determine the GST reporting period.
    # Nullable preserves compatibility with any pre-existing GST records.
    op.add_column(
        "gst_transactions",
        sa.Column(
            "transaction_date",
            sa.Date(),
            nullable=True,
        ),
    )
    op.add_column(
        "gst_transactions",
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Used by GST summary and export queries.
    op.create_index(
        "ix_gst_transactions_tenant_period",
        "gst_transactions",
        ["tenant_id", "reporting_period"],
        unique=False,
    )
    op.create_index(
        "ix_gst_transactions_tenant_date",
        "gst_transactions",
        ["tenant_id", "transaction_date"],
        unique=False,
    )

    # One source document may have multiple GST codes, but each code should only
    # produce one aggregated GST transaction for that document.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_gst_transactions_tenant_source_code "
        "ON gst_transactions "
        "(tenant_id, source_type, source_id, gst_code_id)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS "
        "uq_gst_transactions_tenant_source_code"
    )

    op.drop_index(
        "ix_gst_transactions_tenant_date",
        table_name="gst_transactions",
    )
    op.drop_index(
        "ix_gst_transactions_tenant_period",
        table_name="gst_transactions",
    )

    op.drop_column("gst_transactions", "created_at")
    op.drop_column("gst_transactions", "transaction_date")

    op.drop_index(
        "ix_credit_note_lines_gst_code_id",
        table_name="credit_note_lines",
    )
    op.drop_constraint(
        "fk_credit_note_lines_gst_code_id",
        "credit_note_lines",
        type_="foreignkey",
    )
    op.drop_column("credit_note_lines", "gst_code_id")

    op.drop_index(
        "ix_bill_lines_gst_code_id",
        table_name="bill_lines",
    )
    op.drop_constraint(
        "fk_bill_lines_gst_code_id",
        "bill_lines",
        type_="foreignkey",
    )
    op.drop_column("bill_lines", "gst_code_id")

    op.drop_index(
        "ix_invoice_lines_gst_code_id",
        table_name="invoice_lines",
    )
    op.drop_constraint(
        "fk_invoice_lines_gst_code_id",
        "invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("invoice_lines", "gst_code_id")

    op.drop_column("gst_codes", "is_active")