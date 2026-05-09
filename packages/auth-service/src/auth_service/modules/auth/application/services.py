"""Auth application services."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import bcrypt
import structlog
from accounting_shared.exceptions import ValidationError
from accounting_shared.types import UserId, new_user_id
from jose import JWTError, jwt

from auth_service.config import AuthSettings
from auth_service.modules.auth.application.dto import (
    CurrentUserResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from auth_service.modules.auth.domain.entities import User
from auth_service.modules.auth.domain.exceptions import (
    AccountLockedError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
)
from auth_service.modules.auth.domain.repository import UserRepository
from auth_service.modules.auth.domain.value_objects import Email
from auth_service.security.token_hash import hash_opaque_token

logger = structlog.get_logger(__name__)

# Timing normalization for absent accounts (stable bcrypt check cost).
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"__auth_dummy_password__",
    bcrypt.gensalt(rounds=4),
).decode("utf-8")


def _validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    if len(password) > 128:
        raise ValidationError("Password must not exceed 128 characters.")
    if not any(c.isupper() for c in password):
        raise ValidationError("Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        raise ValidationError("Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        raise ValidationError("Password must contain at least one digit.")


class AuthService:
    """Application service for authentication operations."""

    def __init__(
        self,
        settings: AuthSettings,
        user_repository: UserRepository,
    ) -> None:
        self._settings = settings
        self._user_repo = user_repository

    @staticmethod
    def _hash_password(password: str, rounds: int = 12) -> str:
        """Hash a plain-text password using bcrypt."""
        salt = bcrypt.gensalt(rounds=rounds)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def _verify_password(plain: str, hashed: str) -> bool:
        """Verify a plain-text password against a bcrypt hash."""
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

    def _sign_access_token(self, user_id: str, email: str) -> tuple[str, datetime]:
        """Return JWT access token and absolute expiry (UTC)."""
        now = datetime.now(UTC)
        expire = now + timedelta(
            minutes=self._settings.jwt_access_token_expire_minutes,
        )
        payload: dict[str, object] = {
            "sub": user_id,
            "email": email,
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
        }
        token = jwt.encode(
            payload,
            self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
        )
        return token, expire

    def _decode_access_token(self, token: str) -> dict[str, object]:
        """Decode and validate an access JWT."""
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise InvalidTokenError("Token is invalid or expired.") from exc
        return payload

    async def register(self, dto: RegisterRequest) -> UserResponse:
        """Register a new user account."""
        email = Email(str(dto.email))
        _validate_password_strength(dto.password)

        existing = await self._user_repo.get_by_email(email.value)
        if existing is not None:
            raise EmailAlreadyExistsError()

        hashed = self._hash_password(dto.password, self._settings.bcrypt_rounds)

        user_id = new_user_id()
        now = datetime.now(UTC)
        user = User(
            id=user_id,
            email=email.value,
            hashed_password=hashed,
            full_name=dto.full_name,
            email_verified=not self._settings.email_verification_required,
            is_active=True,
            failed_login_attempts=0,
            locked_until=None,
            created_at=now,
            updated_at=now,
        )

        persisted = await self._user_repo.add(user)

        if self._settings.email_verification_required:
            raw_token = secrets.token_urlsafe(32)
            token_hash = hash_opaque_token(self._settings.jwt_secret, raw_token)
            expires_at = now + timedelta(
                hours=self._settings.email_verification_token_expire_hours,
            )
            await self._user_repo.save_verification_token(
                persisted.id,
                token_hash,
                expires_at,
            )
            if self._settings.debug:
                logger.info(
                    "email_verification_token_issued",
                    user_id=str(persisted.id),
                    email=persisted.email,
                    verification_token=raw_token,
                )

        return self._user_to_full_response(persisted)

    async def login(self, dto: LoginRequest) -> TokenResponse:
        """Authenticate a user and return tokens."""
        email = Email(str(dto.email))
        now = datetime.now(UTC)

        user = await self._user_repo.get_by_email(email.value)
        if user is None:
            self._verify_password(dto.password, _DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError()

        # Expired lock clears automatically.
        if user.locked_until is not None and user.locked_until <= now:
            await self._user_repo.update_login_security(
                user.id,
                failed_attempts=0,
                locked_until=None,
            )
            user = replace(user, locked_until=None, failed_login_attempts=0)

        if user.locked_until is not None and user.locked_until > now:
            raise AccountLockedError()

        if not user.is_active:
            self._verify_password(dto.password, _DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError()

        if not self._verify_password(dto.password, user.hashed_password):
            attempts = user.failed_login_attempts + 1
            locked_until: datetime | None = None
            if attempts >= self._settings.max_login_attempts:
                locked_until = now + timedelta(
                    minutes=self._settings.login_lockout_minutes,
                )
            await self._user_repo.update_login_security(
                user.id,
                failed_attempts=attempts,
                locked_until=locked_until,
            )
            await self._user_repo.commit()
            raise InvalidCredentialsError()

        if self._settings.email_verification_required and not user.email_verified:
            raise EmailNotVerifiedError()

        await self._user_repo.update_login_security(
            user.id,
            failed_attempts=0,
            locked_until=None,
        )

        access_token, access_expires = self._sign_access_token(
            str(user.id),
            user.email,
        )
        raw_refresh = secrets.token_urlsafe(48)
        refresh_hash = hash_opaque_token(self._settings.jwt_secret, raw_refresh)
        refresh_expires = now + timedelta(
            days=self._settings.jwt_refresh_token_expire_days,
        )
        await self._user_repo.save_refresh_token(
            user.id,
            refresh_hash,
            refresh_expires,
        )

        expires_in = int((access_expires - now).total_seconds())
        refresh_expires_in = int((refresh_expires - now).total_seconds())

        return TokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=raw_refresh,
            refresh_expires_in=refresh_expires_in,
        )

    async def verify_email(self, raw_token: str) -> None:
        """Verify a user's email using a verification token."""
        now = datetime.now(UTC)
        token_hash = hash_opaque_token(self._settings.jwt_secret, raw_token)
        row = await self._user_repo.find_verification_token_by_hash(token_hash)
        if row is None:
            raise InvalidTokenError()

        if row.used_at is not None:
            raise InvalidTokenError("Verification token has already been used.")

        if row.expires_at < now:
            raise InvalidTokenError("Verification token has expired.")

        await self._user_repo.mark_email_verified(row.user_id)
        await self._user_repo.mark_verification_token_used(row.id)

    async def refresh_access_token(self, raw_refresh: str) -> TokenResponse:
        """Issue a new access token using a stored refresh token."""
        now = datetime.now(UTC)
        token_hash = hash_opaque_token(self._settings.jwt_secret, raw_refresh)
        row = await self._user_repo.find_refresh_token_by_hash(token_hash)

        if row is None:
            raise InvalidTokenError()

        if row.revoked_at is not None:
            raise InvalidTokenError()

        if row.expires_at < now:
            raise InvalidTokenError()

        user = await self._user_repo.get_by_id(row.user_id)
        if user is None or not user.is_active:
            raise InvalidTokenError()

        access_token, access_expires = self._sign_access_token(
            str(user.id),
            user.email,
        )
        expires_in = int((access_expires - now).total_seconds())
        return TokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=None,
            refresh_expires_in=None,
        )

    async def logout(self, raw_refresh: str) -> None:
        """Revoke a refresh token if present."""
        token_hash = hash_opaque_token(self._settings.jwt_secret, raw_refresh)
        row = await self._user_repo.find_refresh_token_by_hash(token_hash)
        if row is None:
            return
        await self._user_repo.revoke_refresh_token(row.id)

    async def get_current_user(self, access_token: str) -> CurrentUserResponse:
        """Return the current user from a valid access token."""
        payload = self._decode_access_token(access_token)

        if payload.get("type") != "access":
            raise InvalidTokenError("Token is not an access token.")

        user_id_str = payload.get("sub")
        if user_id_str is None or not isinstance(user_id_str, str):
            raise InvalidTokenError("Token missing subject claim.")

        user = await self._user_repo.get_by_id(UserId(uuid.UUID(user_id_str)))
        if user is None:
            raise InvalidTokenError()

        if not user.is_active:
            raise InvalidTokenError()

        return CurrentUserResponse(
            id=str(user.id),
            email=user.email,
            email_verified=user.email_verified,
        )

    async def verify_access_token_for_gateway(self, access_token: str) -> CurrentUserResponse:
        """Validate JWT for inter-service checks (same rules as /me)."""
        return await self.get_current_user(access_token)

    def _user_to_full_response(self, user: User) -> UserResponse:
        """Convert a User entity to a registration/profile DTO."""
        return UserResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            email_verified=user.email_verified,
            is_active=user.is_active,
            created_at=user.created_at,
        )
