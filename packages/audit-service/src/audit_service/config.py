"""Audit Service configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from accounting_shared.config import SharedSettings

_BACKEND_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class AuditSettings(SharedSettings):  # type: ignore[misc]
    """Audit Service specific settings."""

    model_config = SettingsConfigDict(
        env_file=(".env", _BACKEND_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Audit Service"

    # Shared secret for the internal audit-log write endpoint (service-to-service).
    internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIT_INTERNAL_API_TOKEN",
            "TENANT_INTERNAL_API_TOKEN",
            "internal_api_token",
        ),
        description="Shared secret accepted on X-Internal-Token for POST /audit-logs.",
    )

    # Shared secret used when delegating RBAC checks to tenant-service.
    tenant_internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("TENANT_INTERNAL_API_TOKEN", "internal_api_token"),
        description="Shared secret for /internal/authorization/check (service-to-service).",
    )
