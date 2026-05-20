"""US-3: canonical OWNER/ACCOUNTANT/VIEWER roles + tenant_users indexes."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "tenant_us3_002"
down_revision = "tenant_us2_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tenant_users_tenant_id", "tenant_users", ["tenant_id"], unique=False)

    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE tenant_users SET role = UPPER(role)
            WHERE LOWER(role) IN ('owner', 'accountant', 'viewer')
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE tenant_users SET role = LOWER(role)
            WHERE role IN ('OWNER', 'ACCOUNTANT', 'VIEWER')
        """)
    )

    op.drop_index("ix_tenant_users_tenant_id", table_name="tenant_users")
