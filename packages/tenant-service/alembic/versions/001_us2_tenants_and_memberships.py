"""US-2: tenants and tenant_users with membership constraints."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "tenant_us2_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("uen", sa.String(length=64), nullable=True),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("gst_registered", sa.Boolean(), nullable=False),
        sa.Column("financial_year_start_month", sa.Integer(), nullable=False),
        sa.Column("financial_year_start_day", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_table(
        "tenant_users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_users_tenant_user"),
    )
    op.create_index(op.f("ix_tenant_users_user_id"), "tenant_users", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_users_user_id"), table_name="tenant_users")
    op.drop_table("tenant_users")
    op.drop_table("tenants")
