"""US-22: subscription columns for SaaS billing."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "tenant_us22_004"
down_revision = "tenant_us3_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("plan_tier", sa.String(32), nullable=False, server_default="starter"),
    )
    op.add_column(
        "tenants",
        sa.Column("subscription_status", sa.String(32), nullable=False, server_default="trial"),
    )
    op.add_column(
        "tenants",
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("subscription_ends_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "subscription_ends_at")
    op.drop_column("tenants", "trial_ends_at")
    op.drop_column("tenants", "stripe_subscription_id")
    op.drop_column("tenants", "stripe_customer_id")
    op.drop_column("tenants", "subscription_status")
    op.drop_column("tenants", "plan_tier")
