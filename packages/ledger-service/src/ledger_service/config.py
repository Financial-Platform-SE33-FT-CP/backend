from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from accounting_shared.config import SharedSettings

_BACKEND_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class LedgerSettings(SharedSettings):
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
