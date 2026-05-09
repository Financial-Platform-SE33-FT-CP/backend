"""Unit tests for AuthService with mocked UserRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from accounting_shared.types import new_user_id
from pydantic import SecretStr

from auth_service.config import AuthSettings
from auth_service.modules.auth.application.dto import LoginRequest, RegisterRequest
from auth_service.modules.auth.application.services import AuthService
from auth_service.modules.auth.domain.entities import EmailVerificationCode, User
from auth_service.modules.auth.domain.exceptions import (
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    VerificationCodeError,
    VerificationEmailFailedError,
)
from auth_service.modules.auth.infrastructure.email_service import EmailService
from auth_service.security.token_hash import hash_email_verification_code


def _settings(**kwargs: object) -> AuthSettings:
    defaults: dict[str, object] = {
        "jwt_secret": "secret",
        "jwt_algorithm": "HS256",
        "jwt_access_token_expire_minutes": 30,
        "jwt_refresh_token_expire_days": 7,
        "bcrypt_rounds": 4,
        "email_verification_required": True,
        "email_verify_code_length": 6,
        "email_verify_code_expire_minutes": 10,
        "email_verify_code_max_attempts": 5,
        "email_verify_code_resend_cooldown_seconds": 60,
        "max_login_attempts": 5,
        "login_lockout_minutes": 15,
        "debug": False,
        "app_env": "test",
        "frontend_url": "http://localhost:3000",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "u",
        "smtp_password": SecretStr("p"),
        "smtp_from_email": "from@example.com",
        "smtp_from_name": "App",
        "smtp_use_tls": True,
    }
    defaults.update(kwargs)
    return AuthSettings(**defaults)  # type: ignore[arg-type]


def _email_mock() -> AsyncMock:
    return AsyncMock(spec=EmailService)


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

    svc = AuthService(_settings(), repo, _email_mock())
    with pytest.raises(EmailAlreadyExistsError):
        await svc.register(
            RegisterRequest(email="a@b.com", password="SecurePass1"),
        )


@pytest.mark.asyncio
async def test_register_calls_send_verification_code() -> None:
    repo = AsyncMock()
    repo.get_by_email.return_value = None

    async def _add(user: User) -> User:
        return user

    repo.add.side_effect = _add
    email = _email_mock()
    svc = AuthService(_settings(), repo, email)
    res = await svc.register(RegisterRequest(email="new@example.com", password="SecurePass1"))
    assert res.user.is_email_verified is False
    email.send_verification_code_email.assert_awaited_once()
    args, _kwargs = email.send_verification_code_email.await_args
    assert args[0] == "new@example.com"
    assert len(args[1]) == 6
    assert args[1].isdigit()
    repo.save_email_verification_code.assert_awaited_once()
    repo.commit.assert_awaited_once()
    assert res.verification_code is not None


@pytest.mark.asyncio
async def test_register_production_does_not_return_verification_code() -> None:
    repo = AsyncMock()
    repo.get_by_email.return_value = None

    async def _add(user: User) -> User:
        return user

    repo.add.side_effect = _add
    svc = AuthService(_settings(app_env="production"), repo, _email_mock())
    res = await svc.register(RegisterRequest(email="p@example.com", password="SecurePass1"))
    assert res.verification_code is None


@pytest.mark.asyncio
async def test_register_email_send_failure_raises() -> None:
    repo = AsyncMock()
    repo.get_by_email.return_value = None

    async def _add(user: User) -> User:
        return user

    repo.add.side_effect = _add
    email = _email_mock()
    email.send_verification_code_email.side_effect = OSError("smtp down")
    svc = AuthService(_settings(), repo, email)
    with pytest.raises(VerificationEmailFailedError):
        await svc.register(RegisterRequest(email="e@example.com", password="SecurePass1"))
    repo.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_email_code_wrong_hash_increments() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="a@b.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    row = EmailVerificationCode(
        id=uuid4(),
        user_id=uid,
        code_hash=hash_email_verification_code("secret", uid, "999999"),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        attempt_count=0,
    )
    repo.find_latest_unused_verification_code_for_user.return_value = row
    svc = AuthService(_settings(jwt_secret="secret"), repo, _email_mock())
    with pytest.raises(VerificationCodeError):
        await svc.verify_email_with_code("a@b.com", "123456")
    repo.increment_verification_code_attempts.assert_awaited_once()
    repo.commit.assert_awaited_once()


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

    svc = AuthService(_settings(email_verification_required=True), repo, _email_mock())
    with pytest.raises(EmailNotVerifiedError):
        await svc.login(
            LoginRequest(email="a@b.com", password="SecurePass1"),
        )


@pytest.mark.asyncio
async def test_login_invalid_credentials_unknown_email() -> None:
    repo = AsyncMock()
    repo.get_by_email.return_value = None
    svc = AuthService(_settings(), repo, _email_mock())
    with pytest.raises(InvalidCredentialsError):
        await svc.login(
            LoginRequest(email="missing@b.com", password="SecurePass1"),
        )
