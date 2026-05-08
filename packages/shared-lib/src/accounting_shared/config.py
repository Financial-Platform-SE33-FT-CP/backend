"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SharedSettings(BaseSettings):
    """Shared application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "Accounting Platform"
    app_env: str = "development"
    debug: bool = True

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = "DEBUG"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://localhost:5432/accounting"
    database_pool_size: int = 5
    database_pool_overflow: int = 10

    # ── JWT ──────────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # ── Internal services ────────────────────────────────────────────────────
    auth_service_url: str = "http://auth-service:8000"
    tenant_service_url: str = "http://tenant-service:8000"

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["*"]
