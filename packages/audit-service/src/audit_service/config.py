"""Audit Service configuration."""

from __future__ import annotations

from accounting_shared.config import SharedSettings


class AuditSettings(SharedSettings):  # type: ignore[misc]
    """Audit Service specific settings."""

    app_name: str = "Audit Service"
