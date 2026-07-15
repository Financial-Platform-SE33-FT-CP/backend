"""US-13/US-14: Bank CSV upload + reconciliation columns.

Adds columns needed for bank statement uploads (checksum_hash for
duplicate detection, upload_batch_id for batch grouping) and
reconciliation tracking (reconciliation_entity_type/entity_id for
storing the matched invoice/payment reference).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ar_ap_006_bank_reconciliation"
down_revision = "ar_ap_005_credit_note_us10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bank_transactions",
        sa.Column(
            "checksum_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hex digest of (date, description, amount) for duplicate detection",
        ),
    )
    op.add_column(
        "bank_transactions",
        sa.Column(
            "upload_batch_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
            comment="Groups transactions from a single CSV upload",
        ),
    )
    op.add_column(
        "bank_transactions",
        sa.Column(
            "reconciliation_entity_type",
            sa.String(length=32),
            nullable=True,
            comment="Type of matched entity: 'invoice', 'payment', 'bill'",
        ),
    )
    op.add_column(
        "bank_transactions",
        sa.Column(
            "reconciliation_entity_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
            comment="ID of the matched invoice, payment, or bill",
        ),
    )
    op.add_column(
        "bank_transactions",
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_bank_transactions_checksum_hash",
        "bank_transactions",
        ["tenant_id", "checksum_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bank_transactions_checksum_hash", table_name="bank_transactions")
    op.drop_column("bank_transactions", "created_at")
    op.drop_column("bank_transactions", "reconciliation_entity_id")
    op.drop_column("bank_transactions", "reconciliation_entity_type")
    op.drop_column("bank_transactions", "upload_batch_id")
    op.drop_column("bank_transactions", "checksum_hash")
