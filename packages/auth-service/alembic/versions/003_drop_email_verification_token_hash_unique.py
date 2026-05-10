"""Drop unique on email_verification_tokens.token_hash (resend may repeat same code)."""

from __future__ import annotations

from alembic import op

revision = "003_drop_email_code_hash_uq"
down_revision = "002_email_code_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_email_verification_tokens_token_hash",
        "email_verification_tokens",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_email_verification_tokens_token_hash",
        "email_verification_tokens",
        ["token_hash"],
    )
