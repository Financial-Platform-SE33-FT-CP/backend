from __future__ import annotations

from pathlib import Path

from accounting_shared.config import SharedSettings
from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

# Resolve workspace `.env` when uvicorn cwd is not the monorepo root (see AGENTS.md).
_BACKEND_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class COASettings(SharedSettings):
    """Chart-of-accounts service settings."""

    model_config = SettingsConfigDict(
        env_file=(".env", _BACKEND_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    tenant_internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("TENANT_INTERNAL_API_TOKEN", "internal_api_token"),
        description="Must match TenantSettings.internal_api_token for RBAC delegation (US-3).",
    )

    default_coa_accounts: list[dict] = [
        {
            "code": "1000",
            "name": "Cash",
            "type": "asset",
            "description": "Cash and cash equivalents",
        },
        {
            "code": "1200",
            "name": "Accounts Receivable",
            "type": "asset",
            "description": "Trade receivables",
        },
        {
            "code": "2000",
            "name": "Accounts Payable",
            "type": "liability",
            "description": "Short-term payables",
        },
        {
            "code": "3000",
            "name": "Owner's Equity",
            "type": "equity",
            "description": "Owner's capital",
        },
        {"code": "4000", "name": "Revenue", "type": "revenue", "description": "Operating revenue"},
        {
            "code": "5000",
            "name": "Operating Expenses",
            "type": "expense",
            "description": "General operating expenses",
        },
    ]
