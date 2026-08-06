"""Audit log query indexes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "audit_us2_002"
down_revision = "audit_us2_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index for the tenant-scoped listing query, newest first.
    op.create_index(
        "ix_audit_logs_tenant_timestamp",
        "audit_logs",
        ["tenant_id", sa.text("timestamp DESC")],
        unique=False,
    )
    # Lookup index for entity-scoped queries (e.g. "all changes to invoice X").
    op.create_index(
        "ix_audit_logs_entity",
        "audit_logs",
        ["entity_type", "entity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_timestamp", table_name="audit_logs")
