"""Integration tests for US-1 registration, verification, login, tokens, and /me."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_service.modules.auth.infrastructure.models import (
    RefreshTokenModel,
    UserModel,
    VerificationTokenModel,
)


def _sessionmaker(engine: object) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]


def _patch_fixed_verification_code(monkeypatch: pytest.MonkeyPatch, code: str = "123456") -> None:
    monkeypatch.setattr(
        "auth_service.modules.auth.application.services._generate_numeric_verification_code",
        lambda _length: code,
    )


async def _fetch_user(engine: object, email: str) -> UserModel | None:
    sf = _sessionmaker(engine)
    async with sf() as session:
        result = await session.execute(select(UserModel).where(UserModel.email == email))
        return result.scalars().first()


async def _fetch_verification(engine: object, email: str) -> VerificationTokenModel | None:
    sf = _sessionmaker(engine)
    async with sf() as session:
        result = await session.execute(
            select(VerificationTokenModel)
            .join(UserModel, VerificationTokenModel.user_id == UserModel.id)
            .where(UserModel.email == email)
            .order_by(VerificationTokenModel.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()


async def _update_verification_expiry(
    engine: object,
    email: str,
    *,
    expires_at: datetime,
) -> None:
    sf = _sessionmaker(engine)
    async with sf() as session:
        result = await session.execute(
            select(VerificationTokenModel)
            .join(UserModel, VerificationTokenModel.user_id == UserModel.id)
            .where(UserModel.email == email)
            .order_by(VerificationTokenModel.created_at.desc())
            .limit(1)
        )
        vt = result.scalars().first()
        assert vt is not None
        vt.expires_at = expires_at
        await session.commit()


VALID_PASSWORD = "SecurePass1"
FIXED_CODE = "123456"


def test_weak_password_rejected(client: TestClient) -> None:
    r = client.post(
        "/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )
    assert r.status_code == 422


def test_register_creates_unverified_user(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    r = client.post(
        "/auth/register",
        json={"email": "owner@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["is_email_verified"] is False
    assert body["user"]["email"] == "owner@example.com"
    client.email_send_mock.assert_awaited_once()  # type: ignore[attr-defined]


def test_register_response_excludes_secrets(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    r = client.post(
        "/auth/register", json={"email": "safe@example.com", "password": VALID_PASSWORD}
    )
    assert r.status_code == 201
    body = r.json()
    dumped = str(body)
    assert "password_hash" not in dumped
    assert "hashed_password" not in dumped
    assert "token_hash" not in dumped
    assert "code_hash" not in dumped


def test_production_register_omits_verification_code(client_production: TestClient) -> None:
    r = client_production.post(
        "/auth/register",
        json={"email": "prod@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 201
    body = r.json()
    assert "verification_code" not in body
    assert body["message"] == (
        "Registration successful. Please check your email for the verification code."
    )


def test_non_production_register_includes_verification_code(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    r = client.post(
        "/auth/register",
        json={"email": "devtok@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 201
    body = r.json()
    assert body.get("verification_code") == FIXED_CODE


def test_register_email_send_failure_returns_503(client_email_fail: TestClient) -> None:
    r = client_email_fail.post(
        "/auth/register",
        json={"email": "failmail@example.com", "password": VALID_PASSWORD},
    )
    assert r.status_code == 503
    assert "verification email could not be sent" in r.json()["detail"].lower()

    engine = client_email_fail.app.state.engine

    async def _check() -> None:
        user = await _fetch_user(engine, "failmail@example.com")
        assert user is not None
        assert user.email_verified is False

    asyncio.run(_check())


def test_duplicate_email_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    payload = {"email": "dup@example.com", "password": VALID_PASSWORD}
    assert client.post("/auth/register", json=payload).status_code == 201
    r = client.post("/auth/register", json=payload)
    assert r.status_code == 409


def test_password_is_bcrypt_hashed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "hash@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    engine = client.app.state.engine

    async def _check() -> None:
        user = await _fetch_user(engine, email)
        assert user is not None
        assert user.hashed_password.startswith("$2")
        assert user.hashed_password != VALID_PASSWORD

    asyncio.run(_check())


def test_login_before_verification_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "nv@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    r = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    assert r.status_code == 401


def test_verify_email_code_success_and_login(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "ok@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})

    v = client.post(
        "/auth/verify-email-code",
        json={"email": email, "code": FIXED_CODE},
    )
    assert v.status_code == 200
    assert "verified successfully" in v.json()["message"].lower()

    login = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    assert login.status_code == 200
    data = login.json()
    assert "access_token" in data
    assert data.get("refresh_token")
    assert data["token_type"] == "bearer"
    assert data.get("expires_in", 0) > 0
    assert data.get("refresh_expires_in", 0) > 0


def test_verify_email_code_invalid(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "badcode@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    r = client.post(
        "/auth/verify-email-code",
        json={"email": email, "code": "999999"},
    )
    assert r.status_code == 401


def test_verify_email_code_unknown_email_generic_error(client: TestClient) -> None:
    r = client.post(
        "/auth/verify-email-code",
        json={"email": "nobody@example.com", "code": FIXED_CODE},
    )
    assert r.status_code == 401


def test_expired_verification_code(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "exp@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    engine = client.app.state.engine
    past = datetime.now(UTC) - timedelta(minutes=30)
    asyncio.run(_update_verification_expiry(engine, email, expires_at=past))

    r = client.post(
        "/auth/verify-email-code",
        json={"email": email, "code": FIXED_CODE},
    )
    assert r.status_code == 401


def test_used_verification_code_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "used@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    assert (
        client.post(
            "/auth/verify-email-code",
            json={"email": email, "code": FIXED_CODE},
        ).status_code
        == 200
    )
    r = client.post(
        "/auth/verify-email-code",
        json={"email": email, "code": FIXED_CODE},
    )
    assert r.status_code == 401


def test_too_many_wrong_code_attempts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "attempts-code@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    for _ in range(5):
        assert (
            client.post(
                "/auth/verify-email-code",
                json={"email": email, "code": "111111"},
            ).status_code
            == 401
        )
    r = client.post(
        "/auth/verify-email-code",
        json={"email": email, "code": FIXED_CODE},
    )
    assert r.status_code == 401


def test_resend_verification_generic_unknown_email(client: TestClient) -> None:
    r = client.post(
        "/auth/resend-verification-code",
        json={"email": "ghost-nope@example.com"},
    )
    assert r.status_code == 200
    assert "message" in r.json()
    msg = r.json()["message"]
    assert "exists" in msg.lower() or "not verified" in msg.lower()


def test_resend_verification_sends_for_unverified_user(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "resend@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    assert client.email_send_mock.await_count == 1  # type: ignore[attr-defined]
    r = client.post("/auth/resend-verification-code", json={"email": email})
    assert r.status_code == 200
    assert client.email_send_mock.await_count == 2  # type: ignore[attr-defined]


def test_resend_does_not_send_when_already_verified(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "resend-verified@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    count_after_verify = client.email_send_mock.await_count  # type: ignore[attr-defined]
    r = client.post("/auth/resend-verification-code", json={"email": email})
    assert r.status_code == 200
    assert client.email_send_mock.await_count == count_after_verify  # type: ignore[attr-defined]


def test_register_sends_numeric_code_to_email_service(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    client.post("/auth/register", json={"email": "body@example.com", "password": VALID_PASSWORD})
    call = client.email_send_mock.await_args  # type: ignore[attr-defined]
    assert call is not None
    assert call[0][1] == FIXED_CODE


def test_invalid_password_increments_attempts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "attempts@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    engine = client.app.state.engine

    r = client.post("/auth/login", json={"email": email, "password": "WrongPass1"})
    assert r.status_code == 401

    async def _read() -> None:
        user = await _fetch_user(engine, email)
        assert user is not None
        assert user.failed_login_attempts == 1

    asyncio.run(_read())


def test_account_locks_after_max_attempts(
    client_lock_two: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "lock@example.com"
    _patch_fixed_verification_code(monkeypatch)
    tc = client_lock_two
    tc.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    tc.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})

    assert (
        tc.post(
            "/auth/login",
            json={"email": email, "password": "WrongPass1"},
        ).status_code
        == 401
    )
    assert (
        tc.post(
            "/auth/login",
            json={"email": email, "password": "WrongPass1"},
        ).status_code
        == 401
    )
    locked = tc.post(
        "/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert locked.status_code == 401


def test_successful_login_resets_failed_attempts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "reset@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    engine = client.app.state.engine

    client.post("/auth/login", json={"email": email, "password": "WrongPass1"})
    ok = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    assert ok.status_code == 200

    async def _read() -> None:
        user = await _fetch_user(engine, email)
        assert user is not None
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    asyncio.run(_read())


def test_refresh_returns_new_access_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "refresh@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    login = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    refresh_raw = login.json()["refresh_token"]

    time.sleep(1)
    refresh = client.post("/auth/refresh", json={"refresh_token": refresh_raw})
    assert refresh.status_code == 200
    body = refresh.json()
    assert body["access_token"] != login.json()["access_token"]
    assert body.get("refresh_token") is None
    assert body["expires_in"] > 0


def test_logout_revokes_refresh_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "logout@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    login = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    refresh_raw = login.json()["refresh_token"]

    lo = client.post("/auth/logout", json={"refresh_token": refresh_raw})
    assert lo.status_code == 204

    refresh = client.post("/auth/refresh", json={"refresh_token": refresh_raw})
    assert refresh.status_code == 401


def test_me_requires_valid_bearer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "me@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    login = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    token = login.json()["access_token"]

    bad = client.get("/auth/me")
    assert bad.status_code == 401

    bad2 = client.get("/auth/me", headers={"Authorization": "Bearer invalid"})
    assert bad2.status_code == 401

    good = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert good.status_code == 200
    profile = good.json()
    assert profile["email"] == email
    assert profile["email_verified"] is True
    assert "failed_login_attempts" not in profile


def test_access_token_claims_include_email_and_type(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "claims@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    login = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    token = login.json()["access_token"]
    payload = jwt.decode(
        token,
        "unit-test-jwt-secret-not-for-production",
        algorithms=["HS256"],
    )
    assert payload["type"] == "access"
    assert payload["email"] == email
    assert payload["sub"]
    assert "iat" in payload
    assert "exp" in payload


def test_refresh_token_stored_hashed_not_plain(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "store@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    client.post("/auth/verify-email-code", json={"email": email, "code": FIXED_CODE})
    login = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
    refresh_raw = login.json()["refresh_token"]
    engine = client.app.state.engine

    async def _check() -> None:
        sf = _sessionmaker(engine)
        async with sf() as session:
            result = await session.execute(select(RefreshTokenModel))
            rows = result.scalars().all()
            assert len(rows) == 1
            assert refresh_raw not in rows[0].token_hash
            assert len(rows[0].token_hash) == 64

    asyncio.run(_check())


def test_verification_code_stored_hashed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_fixed_verification_code(monkeypatch)
    email = "vh@example.com"
    client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
    engine = client.app.state.engine

    async def _check() -> None:
        vt = await _fetch_verification(engine, email)
        assert vt is not None
        assert vt.code_hash != FIXED_CODE
        assert len(vt.code_hash) == 64

    asyncio.run(_check())


def test_logout_idempotent(client: TestClient) -> None:
    r = client.post("/auth/logout", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 204
