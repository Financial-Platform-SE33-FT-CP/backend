"""US-3: tenant_users.updated_at for membership rows."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "tenant_us3_003"
down_revision = "tenant_us3_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_users",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE tenant_users SET updated_at = created_at WHERE updated_at IS NULL"))
    op.alter_column(
        "tenant_users",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("tenant_users", "updated_at")
