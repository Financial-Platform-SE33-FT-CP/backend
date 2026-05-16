"""AR/AP domain: customers, invoices (extended), lines, AP, banking, GST, payments.

Prerequisite migrations on the same database: tenant (tenants), coa (chart_of_accounts),
ledger (journal_entries).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_001_domain"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("credit_terms_days", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"], unique=False)

    op.create_table(
        "vendors",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_vendors_tenant_id", "vendors", ["tenant_id"], unique=False)

    op.create_table(
        "gst_codes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("rate", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("gst_kind", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_gst_codes_tenant_code"),
    )
    op.create_index("ix_gst_codes_tenant_id", "gst_codes", ["tenant_id"], unique=False)

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_number", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="SGD"),
        sa.Column(
            "opening_balance",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_bank_accounts_tenant_id", "bank_accounts", ["tenant_id"], unique=False)

    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("customer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invoice_number", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("gst_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"], unique=False)

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("invoice_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "quantity",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            server_default="1",
        ),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gst_rate", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["chart_of_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"], unique=False)

    op.create_table(
        "bills",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("vendor_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("bill_number", sa.String(length=100), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unpaid"),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("gst_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_bills_tenant_id", "bills", ["tenant_id"], unique=False)

    op.create_table(
        "bill_lines",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("bill_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("gst_rate", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["chart_of_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bill_id"], ["bills.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_bill_lines_bill_id", "bill_lines", ["bill_id"], unique=False)

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("bank_account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["bank_account_id"],
            ["bank_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_bank_transactions_tenant_id",
        "bank_transactions",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_bank_transactions_bank_account_id",
        "bank_transactions",
        ["bank_account_id"],
        unique=False,
    )

    op.create_table(
        "gst_transactions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("gst_code_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("taxable_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("gst_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reporting_period", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["gst_code_id"], ["gst_codes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_gst_transactions_tenant_id",
        "gst_transactions",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("invoice_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
    )
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payments_tenant_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_gst_transactions_tenant_id", table_name="gst_transactions")
    op.drop_table("gst_transactions")
    op.drop_index("ix_bank_transactions_bank_account_id", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_tenant_id", table_name="bank_transactions")
    op.drop_table("bank_transactions")
    op.drop_index("ix_bill_lines_bill_id", table_name="bill_lines")
    op.drop_table("bill_lines")
    op.drop_index("ix_bills_tenant_id", table_name="bills")
    op.drop_table("bills")
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_tenant_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_bank_accounts_tenant_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")
    op.drop_index("ix_gst_codes_tenant_id", table_name="gst_codes")
    op.drop_table("gst_codes")
    op.drop_index("ix_vendors_tenant_id", table_name="vendors")
    op.drop_table("vendors")
    op.drop_index("ix_customers_tenant_id", table_name="customers")
    op.drop_table("customers")
