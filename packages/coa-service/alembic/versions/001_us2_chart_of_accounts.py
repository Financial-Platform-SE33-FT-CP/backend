"""US-2: chart_of_accounts with tenant scope and unique (tenant_id, code)."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "coa_us2_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chart_of_accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            #sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_system_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_chart_of_accounts_tenant_code"
        ),
    )
    op.create_index(
        op.f("ix_chart_of_accounts_tenant_id"),
        "chart_of_accounts",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chart_of_accounts_tenant_id"), table_name="chart_of_accounts")
    op.drop_table("chart_of_accounts")
