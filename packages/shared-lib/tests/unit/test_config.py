"""Unit tests for accounting_shared.config module."""

from __future__ import annotations

import os
from unittest.mock import patch

from accounting_shared.config import SharedSettings


class TestSharedSettings:
    """Tests for SharedSettings class."""

    def test_default_values(self):
        """SharedSettings should have correct default values."""
        settings = SharedSettings()

        # Application
        assert settings.app_name == "Accounting Platform"
        assert settings.app_env == "development"
        assert settings.debug is True

        # Logging
        assert settings.log_level == "DEBUG"

        # Database
        assert settings.database_url == "postgresql+asyncpg://localhost:5432/accounting"
        assert settings.database_pool_size == 5
        assert settings.database_pool_overflow == 10

        # JWT
        assert settings.jwt_secret == "change-me-in-production"
        assert settings.jwt_algorithm == "HS256"
        assert settings.jwt_access_token_expire_minutes == 30
        assert settings.jwt_refresh_token_expire_days == 7

        # Internal services
        assert settings.auth_service_url == "http://auth-service:8000"
        assert settings.tenant_service_url == "http://tenant-service:8000"

        # CORS
        assert settings.cors_origins == ["*"]

    def test_loads_from_environment_variables(self):
        """SharedSettings should load values from environment variables."""
        env_vars = {
            "APP_NAME": "Test App",
            "APP_ENV": "production",
            "DEBUG": "false",
            "LOG_LEVEL": "INFO",
            "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/testdb",
            "DATABASE_POOL_SIZE": "10",
            "DATABASE_POOL_OVERFLOW": "20",
            "JWT_SECRET": "test-secret-key",
            "JWT_ALGORITHM": "HS512",
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "60",
            "JWT_REFRESH_TOKEN_EXPIRE_DAYS": "30",
            "AUTH_SERVICE_URL": "http://localhost:8001",
            "TENANT_SERVICE_URL": "http://localhost:8002",
            "CORS_ORIGINS": '["http://localhost:3000", "http://localhost:8080"]',
        }

        with patch.dict(os.environ, env_vars, clear=False):
            settings = SharedSettings()

            assert settings.app_name == "Test App"
            assert settings.app_env == "production"
            assert settings.debug is False
            assert settings.log_level == "INFO"
            assert settings.database_url == "postgresql+asyncpg://test:test@localhost:5432/testdb"
            assert settings.database_pool_size == 10
            assert settings.database_pool_overflow == 20
            assert settings.jwt_secret == "test-secret-key"
            assert settings.jwt_algorithm == "HS512"
            assert settings.jwt_access_token_expire_minutes == 60
            assert settings.jwt_refresh_token_expire_days == 30
            assert settings.auth_service_url == "http://localhost:8001"
            assert settings.tenant_service_url == "http://localhost:8002"
            assert settings.cors_origins == ["http://localhost:3000", "http://localhost:8080"]

    def test_app_env_alias_with_env(self):
        """SharedSettings should accept ENV as alias for APP_ENV."""
        with patch.dict(os.environ, {"ENV": "staging"}, clear=False):
            settings = SharedSettings()
            assert settings.app_env == "staging"

    def test_app_env_alias_with_app_env(self):
        """SharedSettings should accept APP_ENV directly."""
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=False):
            settings = SharedSettings()
            assert settings.app_env == "production"

    def test_app_env_prefers_app_env_over_env(self):
        """APP_ENV should take precedence over ENV when both are set."""
        with patch.dict(os.environ, {"APP_ENV": "production", "ENV": "staging"}, clear=False):
            settings = SharedSettings()
            # AliasChoices tries in order, so APP_ENV should win
            assert settings.app_env == "production"

    def test_settings_from_env_file(self, tmp_path):
        """SharedSettings should load from .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "APP_NAME=EnvFileApp\nAPP_ENV=testing\nDEBUG=false\nLOG_LEVEL=WARNING\n"
        )

        # Change to tmp_path to load .env from there
        original_dir = os.getcwd()
        os.chdir(tmp_path)
        try:
            settings = SharedSettings()
            assert settings.app_name == "EnvFileApp"
            assert settings.app_env == "testing"
            assert settings.debug is False
            assert settings.log_level == "WARNING"
        finally:
            os.chdir(original_dir)

    def test_settings_ignore_extra_fields(self):
        """SharedSettings should ignore extra fields."""
        with patch.dict(os.environ, {"UNKNOWN_FIELD": "value"}, clear=False):
            settings = SharedSettings()
            assert not hasattr(settings, "unknown_field")

    def test_settings_model_config(self):
        """SharedSettings should have correct model config."""
        config = SharedSettings.model_config
        assert config.get("extra") == "ignore"
        assert config.get("populate_by_name") is True
        assert config.get("env_file") == ".env"
        assert config.get("env_file_encoding") == "utf-8"
