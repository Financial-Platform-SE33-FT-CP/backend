"""Unit tests for AuthService with mocked UserRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from accounting_shared.types import new_user_id

from auth_service.config import AuthSettings
from auth_service.modules.auth.application.dto import LoginRequest, RegisterRequest
from auth_service.modules.auth.application.services import AuthService
from auth_service.modules.auth.domain.entities import User, VerificationToken
from auth_service.modules.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from auth_service.security.token_hash import hash_opaque_token


def _settings(**kwargs: object) -> AuthSettings:
    defaults: dict[str, object] = {
        "jwt_secret": "secret",
        "jwt_algorithm": "HS256",
        "jwt_access_token_expire_minutes": 30,
        "jwt_refresh_token_expire_days": 7,
        "bcrypt_rounds": 4,
        "email_verification_required": True,
        "email_verification_token_expire_hours": 24,
        "max_login_attempts": 5,
        "login_lockout_minutes": 15,
        "debug": False,
    }
    defaults.update(kwargs)
    return AuthSettings(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_register_raises_when_email_exists() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    existing = User(
        id=uid,
        email="a@b.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = existing

    svc = AuthService(_settings(), repo)
    with pytest.raises(EmailAlreadyExistsError):
        await svc.register(
            RegisterRequest(email="a@b.com", password="SecurePass1"),
        )


@pytest.mark.asyncio
async def test_login_rejects_unverified_when_required() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="a@b.com",
        hashed_password=AuthService._hash_password("SecurePass1", rounds=4),
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user

    svc = AuthService(_settings(email_verification_required=True), repo)
    with pytest.raises(EmailNotVerifiedError):
        await svc.login(
            LoginRequest(email="a@b.com", password="SecurePass1"),
        )


@pytest.mark.asyncio
async def test_login_invalid_credentials_unknown_email() -> None:
    repo = AsyncMock()
    repo.get_by_email.return_value = None
    svc = AuthService(_settings(), repo)
    with pytest.raises(InvalidCredentialsError):
        await svc.login(
            LoginRequest(email="missing@b.com", password="SecurePass1"),
        )


@pytest.mark.asyncio
async def test_verify_email_used_token_raises() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    vt = VerificationToken(
        id=uuid4(),
        user_id=uid,
        token_hash=hash_opaque_token("secret", "raw"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        used_at=datetime.now(UTC),
    )
    repo.find_verification_token_by_hash.return_value = vt

    svc = AuthService(_settings(jwt_secret="secret"), repo)

    with pytest.raises(InvalidTokenError):
        await svc.verify_email("raw")
