from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from accounting_shared.config import SharedSettings

_BACKEND_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class LedgerSettings(SharedSettings):  # type: ignore[misc]
    """Settings for the ledger service."""

    model_config = SettingsConfigDict(
        env_file=(".env", _BACKEND_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    tenant_internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("TENANT_INTERNAL_API_TOKEN", "internal_api_token"),
    )

    # ── Audit trail (EPIC 11) ───────────────────────────────────────────────
    audit_service_url: str = Field(
        default="http://audit-service:8000",
        validation_alias=AliasChoices("AUDIT_SERVICE_URL", "audit_service_url"),
        description="Base URL of the audit-service for audit log emission.",
    )
    audit_internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("AUDIT_INTERNAL_API_TOKEN", "audit_internal_api_token"),
        description=(
            "Shared secret for the audit-service internal endpoint; falls back to "
            "the tenant internal token when unset."
        ),
    )
