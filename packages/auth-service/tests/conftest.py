"""Pytest fixtures for auth-service tests."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_service.modules.auth.infrastructure.models import Base


def _configure_env(
    monkeypatch: pytest.MonkeyPatch,
    sqlite_url: str,
    *,
    max_login_attempts: str = "5",
) -> None:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("JWT_SECRET", "unit-test-jwt-secret-not-for-production")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7")
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "true")
    monkeypatch.setenv("EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS", "24")
    monkeypatch.setenv("MAX_LOGIN_ATTEMPTS", max_login_attempts)
    monkeypatch.setenv("LOGIN_LOCKOUT_MINUTES", "60")
    monkeypatch.setenv("BCRYPT_ROUNDS", "4")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")


async def _create_all(engine: object) -> None:
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    """SQLite file URL shared by the app lifespan and metadata setup."""
    return f"sqlite+aiosqlite:///{tmp_path.joinpath('auth_test.sqlite').as_posix()}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> Iterator[TestClient]:
    """HTTP client against the real app with SQLite backing store."""
    _configure_env(monkeypatch, sqlite_url, max_login_attempts="5")

    from auth_service import deps

    deps.get_settings.cache_clear()

    import auth_service.main as main_mod

    importlib.reload(main_mod)

    with TestClient(main_mod.app) as tc:
        asyncio.run(_create_all(tc.app.state.engine))
        yield tc

    deps.get_settings.cache_clear()


@pytest.fixture
def client_lock_two(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> Iterator[TestClient]:
    """Same as ``client`` but locks after two failed password attempts."""
    _configure_env(monkeypatch, sqlite_url, max_login_attempts="2")

    from auth_service import deps

    deps.get_settings.cache_clear()

    import auth_service.main as main_mod

    importlib.reload(main_mod)

    with TestClient(main_mod.app) as tc:
        asyncio.run(_create_all(tc.app.state.engine))
        yield tc

    deps.get_settings.cache_clear()
