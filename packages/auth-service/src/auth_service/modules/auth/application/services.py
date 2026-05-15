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
    RegisterResponse,
    RegisterUserSnippet,
    TokenResponse,
)
from auth_service.modules.auth.domain.entities import User
from auth_service.modules.auth.domain.exceptions import (
    AccountLockedError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvalidTokenError,
    VerificationCodeError,
    VerificationEmailFailedError,
)
from auth_service.modules.auth.domain.repository import UserRepository
from auth_service.modules.auth.domain.value_objects import Email
from auth_service.modules.auth.infrastructure.email_service import EmailService
from auth_service.security.token_hash import (
    hash_email_verification_code,
    hash_opaque_token,
)

logger = structlog.get_logger(__name__)

_DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"__auth_dummy_password__",
    bcrypt.gensalt(rounds=4),
).decode("utf-8")


def _generate_numeric_verification_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


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


def _is_production(settings: AuthSettings) -> bool:
    return settings.app_env.strip().lower() in ("production", "prod")


class AuthService:
    """Application service for authentication operations."""

    def __init__(
        self,
        settings: AuthSettings,
        user_repository: UserRepository,
        email_service: EmailService,
    ) -> None:
        self._settings = settings
        self._user_repo = user_repository
        self._email_service = email_service

    @staticmethod
    def _hash_password(password: str, rounds: int = 12) -> str:
        salt = bcrypt.gensalt(rounds=rounds)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def _verify_password(plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

    def _sign_access_token(self, user_id: str, email: str) -> tuple[str, datetime]:
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
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            raise InvalidTokenError("Token is invalid or expired.") from exc
        return payload

    def _validate_verification_code_format(self, code: str) -> str:
        normalized = code.strip()
        length = self._settings.email_verify_code_length
        if len(normalized) != length or not normalized.isdigit():
            raise VerificationCodeError()
        return normalized

    async def register(self, dto: RegisterRequest) -> RegisterResponse:
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

        raw_code: str | None = None
        if self._settings.email_verification_required:
            raw_code = _generate_numeric_verification_code(
                self._settings.email_verify_code_length,
            )
            code_hash = hash_email_verification_code(
                self._settings.jwt_secret,
                persisted.id,
                raw_code,
            )
            expires_at = now + timedelta(
                minutes=self._settings.email_verify_code_expire_minutes,
            )
            await self._user_repo.save_email_verification_code(
                persisted.id,
                code_hash,
                expires_at,
                last_sent_at=now,
            )
            await self._user_repo.commit()
            try:
                await self._email_service.send_verification_code_email(
                    persisted.email,
                    raw_code,
                    self._settings.email_verify_code_expire_minutes,
                )
            except Exception as exc:
                logger.exception("verification_email_send_failed", email=persisted.email)
                raise VerificationEmailFailedError() from exc

            if not _is_production(self._settings):
                logger.info(
                    "verification_code_issued_dev",
                    user_id=str(persisted.id),
                    email=persisted.email,
                )

        prod = _is_production(self._settings)
        message = (
            "Registration successful."
            if not self._settings.email_verification_required
            else "Registration successful. Please check your email for the verification code."
        )

        return RegisterResponse(
            message=message,
            user=RegisterUserSnippet(
                id=str(persisted.id),
                email=persisted.email,
                full_name=persisted.full_name,
                is_email_verified=persisted.email_verified,
                is_active=persisted.is_active,
                created_at=persisted.created_at,
            ),
            verification_code=None if prod or raw_code is None else raw_code,
        )

    async def login(self, dto: LoginRequest) -> TokenResponse:
        email = Email(str(dto.email))
        now = datetime.now(UTC)

        user = await self._user_repo.get_by_email(email.value)
        if user is None:
            self._verify_password(dto.password, _DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError()

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

    async def verify_email_with_code(self, email: str, code: str) -> str:
        """Verify email using numeric code. Returns success message or raises VerificationCodeError."""
        em = Email(str(email))
        normalized = self._validate_verification_code_format(code)
        user = await self._user_repo.get_by_email(em.value)
        if user is None or user.email_verified:
            raise VerificationCodeError()

        row = await self._user_repo.find_latest_unused_verification_code_for_user(user.id)
        now = datetime.now(UTC)
        if row is None:
            raise VerificationCodeError()
        if row.attempt_count >= self._settings.email_verify_code_max_attempts:
            raise VerificationCodeError()
        if row.expires_at < now:
            raise VerificationCodeError()

        if (
            hash_email_verification_code(
                self._settings.jwt_secret,
                user.id,
                normalized,
            )
            != row.code_hash
        ):
            await self._user_repo.increment_verification_code_attempts(row.id)
            await self._user_repo.commit()
            raise VerificationCodeError()

        await self._user_repo.mark_email_verified(user.id)
        await self._user_repo.mark_verification_code_used(row.id)
        await self._user_repo.mark_all_pending_verification_codes_used_for_user(user.id)

        return "Email verified successfully. You can now log in."

    RESEND_VERIFICATION_GENERIC_MESSAGE = (
        "If the account exists and is not verified, a new verification code has been sent."
    )

    async def resend_verification_code(self, email: str) -> str:
        """Resend code with generic response and cooldown (anti-enumeration)."""
        try:
            em = Email(str(email))
        except ValidationError:
            return self.RESEND_VERIFICATION_GENERIC_MESSAGE

        user = await self._user_repo.get_by_email(em.value)
        if user is None or user.email_verified:
            return self.RESEND_VERIFICATION_GENERIC_MESSAGE

        now = datetime.now(UTC)
        latest = await self._user_repo.find_latest_verification_code_row_for_user(user.id)
        if (
            latest
            and latest.last_sent_at is not None
            and (now - latest.last_sent_at).total_seconds()
            < self._settings.email_verify_code_resend_cooldown_seconds
        ):
            return self.RESEND_VERIFICATION_GENERIC_MESSAGE

        await self._user_repo.mark_all_pending_verification_codes_used_for_user(user.id)
        raw = _generate_numeric_verification_code(self._settings.email_verify_code_length)
        code_hash = hash_email_verification_code(
            self._settings.jwt_secret,
            user.id,
            raw,
        )
        expires_at = now + timedelta(minutes=self._settings.email_verify_code_expire_minutes)
        await self._user_repo.save_email_verification_code(
            user.id,
            code_hash,
            expires_at,
            last_sent_at=now,
        )
        await self._user_repo.commit()
        try:
            await self._email_service.send_verification_code_email(
                user.email,
                raw,
                self._settings.email_verify_code_expire_minutes,
            )
        except Exception:
            logger.exception("resend_verification_email_failed", email=user.email)
        return self.RESEND_VERIFICATION_GENERIC_MESSAGE

    async def refresh_access_token(self, raw_refresh: str) -> TokenResponse:
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
        token_hash = hash_opaque_token(self._settings.jwt_secret, raw_refresh)
        row = await self._user_repo.find_refresh_token_by_hash(token_hash)
        if row is None:
            return
        await self._user_repo.revoke_refresh_token(row.id)

    async def get_current_user(self, access_token: str) -> CurrentUserResponse:
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
        return await self.get_current_user(access_token)
