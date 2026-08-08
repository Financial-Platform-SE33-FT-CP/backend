"""Billing service configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from accounting_shared.config import SharedSettings

_BACKEND_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class BillingSettings(SharedSettings):  # type: ignore[misc]
    model_config = SettingsConfigDict(
        env_file=(".env", _BACKEND_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_mock_mode: bool = False
    frontend_url: str = "http://localhost:3000"
    stripe_price_ids: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("STRIPE_PRICE_IDS", "stripe_price_ids"),
    )
    tenant_internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("TENANT_INTERNAL_API_TOKEN", "tenant_internal_api_token"),
    )
    tenant_service_url: str = "http://tenant-service:8000"
