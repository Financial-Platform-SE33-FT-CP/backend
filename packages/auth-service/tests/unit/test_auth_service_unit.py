"""Unit tests for AuthService with mocked UserRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from jose import jwt

import pytest
from accounting_shared.types import new_user_id
from pydantic import SecretStr

from auth_service.config import AuthSettings
from auth_service.modules.auth.application.dto import LoginRequest, RegisterRequest
from auth_service.modules.auth.application.services import AuthService
from auth_service.modules.auth.domain.entities import (
    EmailVerificationCode,
    StoredRefreshToken,
    User,
)
from auth_service.modules.auth.domain.exceptions import (
    AccountLockedError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
    VerificationCodeError,
    VerificationEmailFailedError,
)
from auth_service.modules.auth.infrastructure.email_service import EmailService
from auth_service.security.token_hash import (
    hash_email_verification_code,
    hash_opaque_token,
)


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
async def test_register_email_send_failure_returns_success_with_flag() -> None:
    repo = AsyncMock()
    repo.get_by_email.return_value = None

    async def _add(user: User) -> User:
        return user

    repo.add.side_effect = _add
    email = _email_mock()
    email.send_verification_code_email.side_effect = OSError("smtp down")
    svc = AuthService(_settings(), repo, email)
    response = await svc.register(RegisterRequest(email="e@example.com", password="SecurePass1"))

    assert response.verification_email_sent is False
    assert "could not be sent" in response.message.lower()
    repo.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resend_email_send_failure_raises() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="resend@example.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    repo.find_latest_verification_code_row_for_user.return_value = None
    email = _email_mock()
    email.send_verification_code_email.side_effect = OSError("smtp down")
    svc = AuthService(_settings(email_verify_code_resend_cooldown_seconds=0), repo, email)
    with pytest.raises(VerificationEmailFailedError):
        await svc.resend_verification_code("resend@example.com")
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


@pytest.mark.asyncio
async def test_login_invalid_password_locks_account() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="lockable@example.com",
        hashed_password=AuthService._hash_password("SecurePass1", rounds=4),
        email_verified=True,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    svc = AuthService(
        _settings(max_login_attempts=3, login_lockout_minutes=15),
        repo,
        _email_mock(),
    )
    with pytest.raises(InvalidCredentialsError):
        await svc.login(LoginRequest(email="lockable@example.com", password="WrongPass1"))
    repo.update_login_security.assert_awaited_once_with(
        uid,
        failed_attempts=1,
        locked_until=None,
    )


@pytest.mark.asyncio
async def test_login_exceeded_attempts_locks_account() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="lock@example.com",
        hashed_password=AuthService._hash_password("SecurePass1", rounds=4),
        email_verified=True,
        failed_login_attempts=2,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    svc = AuthService(
        _settings(max_login_attempts=3, login_lockout_minutes=15),
        repo,
        _email_mock(),
    )
    with pytest.raises(InvalidCredentialsError):
        await svc.login(LoginRequest(email="lock@example.com", password="WrongPass1"))
    repo.update_login_security.assert_awaited_once()
    _call = repo.update_login_security.await_args
    assert _call is not None
    _kwargs = _call[1]
    assert _kwargs["failed_attempts"] == 3
    assert _kwargs["locked_until"] is not None


@pytest.mark.asyncio
async def test_login_account_locked_rejected() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    now = datetime.now(UTC)
    user = User(
        id=uid,
        email="locked@example.com",
        hashed_password="x",
        email_verified=True,
        failed_login_attempts=3,
        locked_until=now + timedelta(minutes=15),
    )
    repo.get_by_email.return_value = user
    svc = AuthService(_settings(), repo, _email_mock())
    with pytest.raises(AccountLockedError):
        await svc.login(LoginRequest(email="locked@example.com", password="SecurePass1"))


@pytest.mark.asyncio
async def test_login_expired_lock_clears_attempts() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    now = datetime.now(UTC)
    user = User(
        id=uid,
        email="unlocked@example.com",
        hashed_password=AuthService._hash_password("SecurePass1", rounds=4),
        email_verified=True,
        failed_login_attempts=3,
        locked_until=now - timedelta(seconds=1),
    )
    repo.get_by_email.return_value = user
    svc = AuthService(_settings(), repo, _email_mock())
    token_resp = await svc.login(LoginRequest(email="unlocked@example.com", password="SecurePass1"))
    assert token_resp.access_token is not None
    assert token_resp.refresh_token is not None
    repo.update_login_security.assert_awaited_with(
        uid,
        failed_attempts=0,
        locked_until=None,
    )


@pytest.mark.asyncio
async def test_login_inactive_user_rejected() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="inactive@example.com",
        hashed_password=AuthService._hash_password("SecurePass1", rounds=4),
        email_verified=True,
        is_active=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    svc = AuthService(_settings(), repo, _email_mock())
    with pytest.raises(InvalidCredentialsError):
        await svc.login(LoginRequest(email="inactive@example.com", password="SecurePass1"))


@pytest.mark.asyncio
async def test_verify_email_code_expired_rejected() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="expired@example.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    row = EmailVerificationCode(
        id=uuid4(),
        user_id=uid,
        code_hash=hash_email_verification_code("secret", uid, "123456"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        attempt_count=0,
    )
    repo.find_latest_unused_verification_code_for_user.return_value = row
    svc = AuthService(_settings(jwt_secret="secret"), repo, _email_mock())
    with pytest.raises(VerificationCodeError):
        await svc.verify_email_with_code("expired@example.com", "123456")


@pytest.mark.asyncio
async def test_verify_email_code_max_attempts_rejected() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="maxed@example.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    row = EmailVerificationCode(
        id=uuid4(),
        user_id=uid,
        code_hash=hash_email_verification_code("secret", uid, "123456"),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        attempt_count=5,
    )
    repo.find_latest_unused_verification_code_for_user.return_value = row
    svc = AuthService(
        _settings(jwt_secret="secret", email_verify_code_max_attempts=5),
        repo,
        _email_mock(),
    )
    with pytest.raises(VerificationCodeError):
        await svc.verify_email_with_code("maxed@example.com", "123456")


@pytest.mark.asyncio
async def test_verify_email_code_already_verified_rejected() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="done@example.com",
        hashed_password="x",
        email_verified=True,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    svc = AuthService(_settings(), repo, _email_mock())
    with pytest.raises(VerificationCodeError):
        await svc.verify_email_with_code("done@example.com", "123456")


@pytest.mark.asyncio
async def test_verify_email_code_unknown_user_rejected() -> None:
    repo = AsyncMock()
    repo.get_by_email.return_value = None
    svc = AuthService(_settings(), repo, _email_mock())
    with pytest.raises(VerificationCodeError):
        await svc.verify_email_with_code("missing@example.com", "123456")


@pytest.mark.asyncio
async def test_verify_email_code_success() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="success@example.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    row = EmailVerificationCode(
        id=uuid4(),
        user_id=uid,
        code_hash=hash_email_verification_code("secret", uid, "123456"),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        attempt_count=0,
    )
    repo.find_latest_unused_verification_code_for_user.return_value = row
    svc = AuthService(_settings(jwt_secret="secret"), repo, _email_mock())
    msg = await svc.verify_email_with_code("success@example.com", "123456")
    assert "verified" in msg.lower()
    repo.mark_email_verified.assert_awaited_once_with(uid)
    repo.mark_verification_code_used.assert_awaited_once_with(row.id)
    repo.mark_all_pending_verification_codes_used_for_user.assert_awaited_once_with(uid)


@pytest.mark.asyncio
async def test_resend_verification_in_cooldown_does_not_send() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="cooldown@example.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    now = datetime.now(UTC)
    latest = EmailVerificationCode(
        id=uuid4(),
        user_id=uid,
        code_hash="x",
        expires_at=now + timedelta(minutes=10),
        attempt_count=0,
        last_sent_at=now - timedelta(seconds=30),
    )
    repo.find_latest_verification_code_row_for_user.return_value = latest
    email = _email_mock()
    svc = AuthService(
        _settings(email_verify_code_resend_cooldown_seconds=60),
        repo,
        email,
    )
    resp = await svc.resend_verification_code("cooldown@example.com")
    assert email.send_verification_code_email.await_count == 0
    assert "sent" in resp.message.lower() or "verified" in resp.message.lower()


@pytest.mark.asyncio
async def test_resend_verification_after_cooldown_sends() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="aftercooldown@example.com",
        hashed_password="x",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    now = datetime.now(UTC)
    latest = EmailVerificationCode(
        id=uuid4(),
        user_id=uid,
        code_hash="x",
        expires_at=now + timedelta(minutes=10),
        attempt_count=0,
        last_sent_at=now - timedelta(seconds=120),
    )
    repo.find_latest_verification_code_row_for_user.return_value = latest
    email = _email_mock()
    svc = AuthService(
        _settings(email_verify_code_resend_cooldown_seconds=60),
        repo,
        email,
    )
    resp = await svc.resend_verification_code("aftercooldown@example.com")
    email.send_verification_code_email.assert_awaited_once()
    assert resp.verification_code is not None
    repo.save_email_verification_code.assert_awaited_once()
    repo.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_sign_and_decode_access_token_roundtrip() -> None:
    svc = AuthService(_settings(), AsyncMock(), _email_mock())
    uid_str = str(new_user_id())
    email = "token@example.com"
    token, expire = svc._sign_access_token(uid_str, email)
    assert token is not None
    assert expire > datetime.now(UTC)

    payload = svc._decode_access_token(token)
    assert payload["sub"] == uid_str
    assert payload["email"] == email
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_decode_access_token_invalid_raises() -> None:
    svc = AuthService(_settings(), AsyncMock(), _email_mock())
    with pytest.raises(InvalidTokenError):
        svc._decode_access_token("invalid-token")


@pytest.mark.asyncio
async def test_refresh_access_token_from_login() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    now = datetime.now(UTC)
    user = User(
        id=uid,
        email="refresh_login@example.com",
        hashed_password=AuthService._hash_password("SecurePass1", rounds=4),
        email_verified=True,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_email.return_value = user
    repo.get_by_id.return_value = user

    raw_refresh = "test-raw-refresh-token-value"

    refresh_row = StoredRefreshToken(
        id=uuid4(),
        user_id=uid,
        token_hash=hash_opaque_token("secret", raw_refresh),
        expires_at=now + timedelta(days=7),
    )
    repo.find_refresh_token_by_hash.return_value = refresh_row

    svc = AuthService(_settings(jwt_secret="secret"), repo, _email_mock())
    token_resp = await svc.refresh_access_token(raw_refresh)

    assert token_resp.access_token is not None
    assert token_resp.expires_in > 0
    repo.get_by_id.assert_awaited_once_with(uid)


@pytest.mark.asyncio
async def test_refresh_token_revoked_rejected() -> None:
    repo = AsyncMock()
    now = datetime.now(UTC)
    refresh_row = StoredRefreshToken(
        id=uuid4(),
        user_id=new_user_id(),
        token_hash=hash_opaque_token("secret", "revoked-token"),
        expires_at=now + timedelta(days=7),
        revoked_at=now - timedelta(hours=1),
    )
    repo.find_refresh_token_by_hash.return_value = refresh_row
    svc = AuthService(_settings(jwt_secret="secret"), repo, _email_mock())
    with pytest.raises(InvalidTokenError):
        await svc.refresh_access_token("revoked-token")


@pytest.mark.asyncio
async def test_refresh_token_expired_rejected() -> None:
    repo = AsyncMock()
    now = datetime.now(UTC)
    refresh_row = StoredRefreshToken(
        id=uuid4(),
        user_id=new_user_id(),
        token_hash=hash_opaque_token("secret", "expired-token"),
        expires_at=now - timedelta(seconds=1),
    )
    repo.find_refresh_token_by_hash.return_value = refresh_row
    svc = AuthService(_settings(jwt_secret="secret"), repo, _email_mock())
    with pytest.raises(InvalidTokenError):
        await svc.refresh_access_token("expired-token")


@pytest.mark.asyncio
async def test_get_current_user_rejects_non_access_token() -> None:
    svc = AuthService(_settings(), AsyncMock(), _email_mock())
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(new_user_id()),
        "email": "wrong@example.com",
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=30)).timestamp()),
    }
    bad_token = jwt.encode(payload, "secret", algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        await svc.get_current_user(bad_token)


@pytest.mark.asyncio
async def test_get_current_user_inactive_rejected() -> None:
    repo = AsyncMock()
    uid = new_user_id()
    user = User(
        id=uid,
        email="inactive@example.com",
        hashed_password="x",
        email_verified=True,
        is_active=False,
        failed_login_attempts=0,
        locked_until=None,
    )
    repo.get_by_id.return_value = user
    svc = AuthService(_settings(), repo, _email_mock())
    token, _expire = svc._sign_access_token(str(uid), "inactive@example.com")
    with pytest.raises(InvalidTokenError):
        await svc.get_current_user(token)
