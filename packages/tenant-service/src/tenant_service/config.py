from __future__ import annotations

from pathlib import Path

from accounting_shared.config import SharedSettings
from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

# Resolve workspace `.env` when uvicorn cwd is not the monorepo root (see AGENTS.md).
_BACKEND_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class TenantSettings(SharedSettings):
    """Tenant-service specific settings."""

    model_config = SettingsConfigDict(
        env_file=(".env", _BACKEND_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    default_coa_seed: bool = True
    internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("TENANT_INTERNAL_API_TOKEN", "internal_api_token"),
        description="Shared secret for /internal/authorization/check (service-to-service).",
    )

    @property
    def service_name(self) -> str:
        return "tenant-service"
