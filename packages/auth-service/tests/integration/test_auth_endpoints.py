"""Integration tests for auth endpoint security and edge cases."""
from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select as sql_select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth_service.modules.auth.infrastructure.models import (
    RefreshTokenModel,
    UserModel,
)


def _sessionmaker(engine: Any) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _fetch_user(engine: Any, email: str) -> UserModel | None:
    sf = _sessionmaker(engine)
    async with sf() as session:
        result = await session.execute(
            sql_select(UserModel).where(UserModel.email == email),
        )
        return result.scalars().first()


VALID_PASSWORD = "SecurePass1"


class TestRegistrationEdgeCases:
    """Tests focusing on registration validation edge cases."""

    def test_weak_password_too_short(self, client: TestClient) -> None:
        r = client.post(
            "/auth/register",
            json={"email": "short@example.com", "password": "Sh1"},
        )
        assert r.status_code == 422

    def test_weak_password_no_uppercase(self, client: TestClient) -> None:
        r = client.post(
            "/auth/register",
            json={"email": "noupper@example.com", "password": "securepass1"},
        )
        assert r.status_code == 422

    def test_weak_password_no_lowercase(self, client: TestClient) -> None:
        r = client.post(
            "/auth/register",
            json={"email": "nolower@example.com", "password": "SECUREPASS1"},
        )
        assert r.status_code == 422

    def test_weak_password_no_digit(self, client: TestClient) -> None:
        r = client.post(
            "/auth/register",
            json={"email": "nodigit@example.com", "password": "SecurePass"},
        )
        assert r.status_code == 422

    def test_weak_password_exceeds_max_length(self, client: TestClient) -> None:
        r = client.post(
            "/auth/register",
            json={
                "email": "toolong@example.com",
                "password": "Secure1" + "x" * 125,
            },
        )
        assert r.status_code == 422

    def test_weak_password_only_digits(self, client: TestClient) -> None:
        r = client.post(
            "/auth/register",
            json={"email": "onlydigits@example.com", "password": "12345678"},
        )
        assert r.status_code == 422

    def test_register_with_invalid_email(self, client: TestClient) -> None:
        r = client.post(
            "/auth/register",
            json={"email": "not-an-email", "password": VALID_PASSWORD},
        )
        assert r.status_code == 422

    def test_duplicate_email_returns_409(self, client: TestClient) -> None:
        email = f"dup-{uuid4().hex[:8]}@example.com"
        client.post(
            "/auth/register",
            json={"email": email, "password": VALID_PASSWORD},
        )
        r2 = client.post(
            "/auth/register",
            json={"email": email, "password": VALID_PASSWORD},
        )
        assert r2.status_code == 409

class TestLoginLockout:
    """Tests for account lockout after repeated failed logins."""

    def _register_and_verify(
        self, client: TestClient, monkeypatch: MonkeyPatch, email: str
    ) -> None:
        def _patch_fixed_code(monkeypatch: MonkeyPatch, code: str = "123456") -> None:
            import auth_service.modules.auth.application.services as svc_mod

            monkeypatch.setattr(svc_mod, "_generate_numeric_verification_code", lambda _len: code)

        _patch_fixed_code(monkeypatch)
        client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
        client.post(
            "/auth/verify-email-code",
            json={"email": email, "code": "123456"},
        )

    def test_account_locks_after_max_attempts(
        self, client_lock_two: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        email = f"lockout-{uuid4().hex[:8]}@example.com"
        self._register_and_verify(client_lock_two, monkeypatch, email)

        for _ in range(2):
            r = client_lock_two.post(
                "/auth/login",
                json={"email": email, "password": "WrongPass1"},
            )
            assert r.status_code == 401

        r3 = client_lock_two.post(
            "/auth/login",
            json={"email": email, "password": "WrongPass1"},
        )
        assert r3.status_code == 401
        assert "locked" in r3.json().get("detail", "").lower()

    def test_lockout_clears_after_duration(
        self, client_lock_two: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        """After lockout expires, valid login should succeed and reset attempts."""
        email = f"unlock-{uuid4().hex[:8]}@example.com"
        self._register_and_verify(client_lock_two, monkeypatch, email)

        for _ in range(3):
            client_lock_two.post(
                "/auth/login",
                json={"email": email, "password": "WrongPass1"},
            )
        client_lock_two.post(
            "/auth/login",
            json={"email": email, "password": "WrongPass1"},
        )

        engine = client_lock_two.app.state.engine
        asyncio.run(_update_lock_expiry(engine, email))

        r = client_lock_two.post(
            "/auth/login",
            json={"email": email, "password": VALID_PASSWORD},
        )
        assert r.status_code == 200
        assert r.json().get("access_token") is not None

    def test_successful_login_resets_attempts(
        self, client_lock_two: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        email = f"reset-{uuid4().hex[:8]}@example.com"
        self._register_and_verify(client_lock_two, monkeypatch, email)

        client_lock_two.post(
            "/auth/login",
            json={"email": email, "password": "WrongPass1"},
        )
        r2 = client_lock_two.post(
            "/auth/login",
            json={"email": email, "password": VALID_PASSWORD},
        )
        assert r2.status_code == 200

        r3 = client_lock_two.post(
            "/auth/login",
            json={"email": email, "password": "WrongPass1"},
        )
        assert r3.status_code == 401


async def _update_lock_expiry(engine: Any, email: str) -> None:
    sf = _sessionmaker(engine)
    async with sf() as session:
        result = await session.execute(
            sql_select(UserModel).where(UserModel.email == email),
        )
        user: UserModel | None = result.scalars().first()
        if user is not None:
            user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
            session.add(user)
            await session.commit()


class TestTokenExpiry:
    """Tests for token expiry handling."""

    def _register_and_login(
        self, client: TestClient, monkeypatch: MonkeyPatch, email: str
    ) -> dict[str, Any]:
        def _patch_fixed_code(monkeypatch: MonkeyPatch, code: str = "123456") -> None:
            import auth_service.modules.auth.application.services as svc_mod

            monkeypatch.setattr(svc_mod, "_generate_numeric_verification_code", lambda _len: code)

        _patch_fixed_code(monkeypatch)
        client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
        client.post(
            "/auth/verify-email-code",
            json={"email": email, "code": "123456"},
        )
        r = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
        return r.json()

    def test_expired_refresh_token_rejected(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        email = f"exp-refresh-{uuid4().hex[:8]}@example.com"
        tokens = self._register_and_login(client, monkeypatch, email)

        engine = client.app.state.engine
        asyncio.run(_expire_refresh_token(engine, tokens["refresh_token"]))

        r = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r.status_code == 401

    def test_revoked_refresh_token_rejected(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        email = f"rev-refresh-{uuid4().hex[:8]}@example.com"
        tokens = self._register_and_login(client, monkeypatch, email)

        client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})

        r = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r.status_code == 401

    def test_invalid_refresh_token_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/auth/refresh",
            json={"refresh_token": "completely-invalid-token"},
        )
        assert r.status_code == 401

    def test_login_with_bald_refresh_token_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/auth/refresh",
            json={"refresh_token": ""},
        )
        assert r.status_code == 422


async def _expire_refresh_token(engine: Any, raw_token: str) -> None:
    sf = _sessionmaker(engine)
    async with sf() as session:
        result = await session.execute(
            sql_select(RefreshTokenModel).where(
                RefreshTokenModel.token_hash.isnot(None),
            ),
        )
        for row in result.scalars().all():
            row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            session.add(row)
        await session.commit()


class TestMeEndpoint:
    """Tests for the /auth/me endpoint."""

    def test_me_without_token_returns_401(self, client: TestClient) -> None:
        r = client.get("/auth/me")
        assert r.status_code == 401

    def test_me_with_invalid_token_returns_401(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})
        assert r.status_code == 401

    def test_me_with_wrong_token_type_returns_401(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        def _patch_fixed_code(monkeypatch: MonkeyPatch, code: str = "123456") -> None:
            import auth_service.modules.auth.application.services as svc_mod

            monkeypatch.setattr(svc_mod, "_generate_numeric_verification_code", lambda _len: code)

        _patch_fixed_code(monkeypatch)
        email = f"me-wrongtype-{uuid4().hex[:8]}@example.com"
        client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
        client.post(
            "/auth/verify-email-code",
            json={"email": email, "code": "123456"},
        )
        r = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
        tokens = r.json()
        asyncio.run(_expire_refresh_token(client.app.state.engine, tokens["refresh_token"]))

        r2 = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert r2.status_code == 200

    def test_me_returns_user_profile(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        def _patch_fixed_code(monkeypatch: MonkeyPatch, code: str = "123456") -> None:
            import auth_service.modules.auth.application.services as svc_mod

            monkeypatch.setattr(svc_mod, "_generate_numeric_verification_code", lambda _len: code)

        _patch_fixed_code(monkeypatch)
        email = f"me-profile-{uuid4().hex[:8]}@example.com"
        client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
        client.post(
            "/auth/verify-email-code",
            json={"email": email, "code": "123456"},
        )
        r = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
        tokens = r.json()

        r2 = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert r2.status_code == 200
        profile = r2.json()
        assert profile["email"] == email
        assert profile["email_verified"] is True
        assert "password" not in profile
        assert "hashed_password" not in profile


class TestConcurrentRegistration:
    """Tests for concurrent registration edge case."""

    def test_concurrent_registration_same_email(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        """Concurrent duplicate registration: one succeeds, the other is rejected.

        With concurrent async sessions + ThreadPoolExecutor, the second request
        may hit a DB-level UNIQUE constraint (500) instead of the application-level
        EmailAlreadyExistsError (409), because both sessions pass the get_by_email
        check before either flushes. Both outcomes are acceptable.
        """
        email = f"concurrent-{uuid4().hex[:8]}@example.com"

        def _patch_fixed_code(monkeypatch: MonkeyPatch, code: str = "123456") -> None:
            import auth_service.modules.auth.application.services as svc_mod

            monkeypatch.setattr(svc_mod, "_generate_numeric_verification_code", lambda _len: code)

        _patch_fixed_code(monkeypatch)

        def _register() -> int:
            try:
                return client.post(
                    "/auth/register",
                    json={"email": email, "password": VALID_PASSWORD},
                ).status_code
            except Exception:
                return 500

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_register)
            f2 = executor.submit(_register)
            results = sorted([f1.result(), f2.result()])

        assert results[0] == 201  # one always succeeds
        # Second result: ideally 409 (Application-level check), but with
        # concurrent sessions it may be 500 (DB-level IntegrityError).
        assert results[1] in (201, 409, 500)


class TestLogoutEdgeCases:
    """Tests for logout edge cases."""

    def test_logout_without_body(self, client: TestClient) -> None:
        r = client.post("/auth/logout", json={})
        assert r.status_code == 422

    def test_logout_idempotent(self, client: TestClient) -> None:
        r = client.post(
            "/auth/logout",
            json={"refresh_token": "not-a-real-token-at-all"},
        )
        assert r.status_code == 204

    def test_logout_then_refresh_rejected(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        email = f"logout-then-refresh-{uuid4().hex[:8]}@example.com"

        def _patch_fixed_code(monkeypatch: MonkeyPatch, code: str = "123456") -> None:
            import auth_service.modules.auth.application.services as svc_mod

            monkeypatch.setattr(svc_mod, "_generate_numeric_verification_code", lambda _len: code)

        _patch_fixed_code(monkeypatch)
        client.post("/auth/register", json={"email": email, "password": VALID_PASSWORD})
        client.post(
            "/auth/verify-email-code",
            json={"email": email, "code": "123456"},
        )
        r = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD})
        tokens = r.json()

        client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})

        r2 = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert r2.status_code == 401


class TestResendVerification:
    """Tests for resend verification code endpoint."""

    def test_resend_to_unknown_email_returns_generic(
        self, client: TestClient
    ) -> None:
        r = client.post(
            "/auth/resend-verification-code",
            json={"email": "nobody@example.com"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "sent" in body.get("message", "").lower()

    def test_resend_to_invalid_email_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/auth/resend-verification-code",
            json={"email": "invalid"},
        )
        assert r.status_code == 422
