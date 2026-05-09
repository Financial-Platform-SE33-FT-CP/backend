"""Auth service configuration."""

from accounting_shared.config import SharedSettings
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import SettingsConfigDict


class AuthSettings(SharedSettings):
    """Auth-service-specific settings extending shared configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Bcrypt
    bcrypt_rounds: int = Field(default=12, alias="BCRYPT_ROUNDS")

    # Optional public URL (not used for verification emails in code-based flow).
    auth_service_public_url: str = Field(default="", alias="AUTH_SERVICE_PUBLIC_URL")

    frontend_url: str = Field(
        default="http://localhost:3000",
        alias="FRONTEND_URL",
    )

    # SMTP (fastapi-mail / aiosmtplib)
    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: SecretStr = Field(default=SecretStr(""), alias="SMTP_PASSWORD")
    smtp_from_email: str = Field(default="noreply@example.com", alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="Accounting Platform", alias="SMTP_FROM_NAME")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")

    # Email verification (numeric code)
    email_verification_required: bool = Field(
        default=True,
        alias="EMAIL_VERIFICATION_REQUIRED",
    )
    email_verify_code_length: int = Field(
        default=6,
        ge=4,
        le=12,
        alias="AUTH_EMAIL_VERIFY_CODE_LENGTH",
    )
    email_verify_code_expire_minutes: int = Field(
        default=10,
        ge=1,
        alias="AUTH_EMAIL_VERIFY_CODE_EXPIRE_MINUTES",
    )
    email_verify_code_max_attempts: int = Field(
        default=5,
        ge=1,
        alias="AUTH_EMAIL_VERIFY_CODE_MAX_ATTEMPTS",
    )
    email_verify_code_resend_cooldown_seconds: int = Field(
        default=60,
        ge=0,
        alias="AUTH_EMAIL_VERIFY_CODE_RESEND_COOLDOWN_SECONDS",
    )
    # Legacy alias (unused for code flow); kept so old .env keys do not break startup.
    email_verification_token_expire_hours: int = Field(
        default=24,
        validation_alias=AliasChoices(
            "AUTH_EMAIL_VERIFY_TOKEN_EXPIRE_HOURS",
            "EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS",
        ),
    )

    # Login rate limiting
    max_login_attempts: int = Field(default=5, alias="MAX_LOGIN_ATTEMPTS")
    login_lockout_minutes: int = Field(default=15, alias="LOGIN_LOCKOUT_MINUTES")
