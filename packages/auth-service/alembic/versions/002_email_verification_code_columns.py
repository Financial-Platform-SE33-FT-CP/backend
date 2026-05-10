"""Add attempt_count, last_sent_at, purpose to email_verification_tokens."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "002_email_code_cols"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_verification_tokens",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "email_verification_tokens",
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_verification_tokens",
        sa.Column(
            "purpose",
            sa.String(length=64),
            nullable=False,
            server_default="email_verification",
        ),
    )
    op.alter_column("email_verification_tokens", "attempt_count", server_default=None)
    op.alter_column("email_verification_tokens", "purpose", server_default=None)


def downgrade() -> None:
    op.drop_column("email_verification_tokens", "purpose")
    op.drop_column("email_verification_tokens", "last_sent_at")
    op.drop_column("email_verification_tokens", "attempt_count")
