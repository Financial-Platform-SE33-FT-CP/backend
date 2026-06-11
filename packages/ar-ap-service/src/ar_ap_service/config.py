"""AR/AP Service configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from accounting_shared.config import SharedSettings

_BACKEND_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class ArApSettings(SharedSettings):  # type: ignore[misc]
    """Settings for the AR/AP service."""

    model_config = SettingsConfigDict(
        env_file=(".env", _BACKEND_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    tenant_internal_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("TENANT_INTERNAL_API_TOKEN", "internal_api_token"),
        description="Must match the tenant-service internal token for RBAC delegation (US-3).",
    )

    # Control accounts used when posting invoice journal entries. Resolved per
    # tenant by code so each tenant can map them onto its own Chart of Accounts.
    ar_control_account_code: str = Field(
        default="1100",
        validation_alias=AliasChoices("AR_CONTROL_ACCOUNT_CODE"),
        description="Chart-of-accounts code for the Accounts Receivable control account.",
    )
    gst_output_account_code: str = Field(
        default="2100",
        validation_alias=AliasChoices("GST_OUTPUT_ACCOUNT_CODE"),
        description="Chart-of-accounts code for the GST Output Tax liability account.",
    )
    ap_control_account_code: str = Field(
        default="2000",
        validation_alias=AliasChoices("AP_CONTROL_ACCOUNT_CODE"),
        description="Chart-of-accounts code for the Accounts Payable control account.",
    )
    gst_input_account_code: str = Field(
        default="1200",
        validation_alias=AliasChoices("GST_INPUT_ACCOUNT_CODE"),
        description="Chart-of-accounts code for the GST Input Tax asset account.",
    )
