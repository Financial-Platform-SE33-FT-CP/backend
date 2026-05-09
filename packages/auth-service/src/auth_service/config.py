"""Auth service configuration."""

from accounting_shared.config import SharedSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class AuthSettings(SharedSettings):
    """Auth-service-specific settings extending shared configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bcrypt
    bcrypt_rounds: int = Field(default=12, alias="BCRYPT_ROUNDS")

    # Email verification
    email_verification_required: bool = Field(
        default=True,
        alias="EMAIL_VERIFICATION_REQUIRED",
    )
    email_verification_token_expire_hours: int = Field(
        default=24,
        alias="EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS",
    )

    # Login rate limiting
    max_login_attempts: int = Field(default=5, alias="MAX_LOGIN_ATTEMPTS")
    login_lockout_minutes: int = Field(default=15, alias="LOGIN_LOCKOUT_MINUTES")
