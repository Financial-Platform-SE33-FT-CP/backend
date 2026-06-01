"""SQLAlchemy implementation of the UserRepository interface."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from accounting_shared.types import UserId
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.modules.auth.domain.entities import (
    EmailVerificationCode,
    StoredRefreshToken,
    User,
)
from auth_service.modules.auth.domain.repository import UserRepository
from auth_service.modules.auth.infrastructure.models import (
    RefreshTokenModel,
    UserModel,
    VerificationTokenModel,
)


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite may return naive datetimes; domain logic uses UTC-aware values."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy-backed user repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()

    async def get_by_email(self, email: str) -> User | None:
        """Retrieve a user by email address."""
        result = await self._session.execute(select(UserModel).where(UserModel.email == email))
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_id(self, id: UserId) -> User | None:  # noqa: A002
        """Retrieve a user by their unique identifier."""
        result = await self._session.execute(select(UserModel).where(UserModel.id == id))
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def add(self, user: User) -> User:
        """Persist a new user."""
        model = UserModel(
            id=user.id,
            email=user.email,
            hashed_password=user.hashed_password,
            full_name=user.full_name,
            email_verified=user.email_verified,
            is_active=user.is_active,
            failed_login_attempts=user.failed_login_attempts,
            locked_until=user.locked_until,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)

    async def update(self, user: User) -> User:
        """Update an existing user."""
        result = await self._session.execute(select(UserModel).where(UserModel.id == user.id))
        model = result.scalars().first()
        if model is None:
            raise ValueError(f"User with id {user.id} not found.")

        model.email = user.email
        model.hashed_password = user.hashed_password
        model.full_name = user.full_name
        model.email_verified = user.email_verified
        model.is_active = user.is_active
        model.failed_login_attempts = user.failed_login_attempts
        model.locked_until = user.locked_until
        model.updated_at = datetime.now(UTC)

        await self._session.flush()
        return self._to_domain(model)

    async def delete(self, user: User) -> None:
        """Remove a user row."""
        result = await self._session.execute(select(UserModel).where(UserModel.id == user.id))
        model = result.scalars().first()
        if model is None:
            return
        self._session.delete(model)
        await self._session.flush()

    async def save_email_verification_code(
        self,
        user_id: UserId,
        code_hash: str,
        expires_at: datetime,
        *,
        last_sent_at: datetime,
        purpose: str = "email_verification",
    ) -> None:
        """Persist a new email verification code hash."""
        model = VerificationTokenModel(
            user_id=user_id,
            code_hash=code_hash,
            expires_at=expires_at,
            used_at=None,
            attempt_count=0,
            last_sent_at=last_sent_at,
            purpose=purpose,
        )
        self._session.add(model)
        await self._session.flush()

    async def find_latest_unused_verification_code_for_user(
        self,
        user_id: UserId,
    ) -> EmailVerificationCode | None:
        """Return the newest unused verification code row for this user."""
        result = await self._session.execute(
            select(VerificationTokenModel)
            .where(
                VerificationTokenModel.user_id == user_id,
                VerificationTokenModel.used_at.is_(None),
            )
            .order_by(VerificationTokenModel.created_at.desc())
            .limit(1)
        )
        model = result.scalars().first()
        return self._verification_to_domain(model) if model else None

    async def find_latest_verification_code_row_for_user(
        self,
        user_id: UserId,
    ) -> EmailVerificationCode | None:
        """Return the newest verification row for cooldown."""
        result = await self._session.execute(
            select(VerificationTokenModel)
            .where(VerificationTokenModel.user_id == user_id)
            .order_by(VerificationTokenModel.created_at.desc())
            .limit(1)
        )
        model = result.scalars().first()
        return self._verification_to_domain(model) if model else None

    async def increment_verification_code_attempts(self, code_id: uuid.UUID) -> None:
        """Increment wrong-code attempt counter."""
        result = await self._session.execute(
            select(VerificationTokenModel).where(VerificationTokenModel.id == code_id)
        )
        model = result.scalars().first()
        if model is None:
            return
        model.attempt_count += 1
        await self._session.flush()

    async def mark_verification_code_used(self, code_id: uuid.UUID) -> None:
        """Mark a verification code as consumed."""
        result = await self._session.execute(
            select(VerificationTokenModel).where(VerificationTokenModel.id == code_id)
        )
        model = result.scalars().first()
        if model is None:
            return
        model.used_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_all_pending_verification_codes_used_for_user(
        self,
        user_id: UserId,
        *,
        except_code_id: uuid.UUID | None = None,
    ) -> None:
        """Invalidate pending codes."""
        now = datetime.now(UTC)
        stmt = (
            update(VerificationTokenModel)
            .where(
                VerificationTokenModel.user_id == user_id,
                VerificationTokenModel.used_at.is_(None),
            )
            .values(used_at=now)
        )
        if except_code_id is not None:
            stmt = stmt.where(VerificationTokenModel.id != except_code_id)
        await self._session.execute(stmt)
        await self._session.flush()

    async def mark_email_verified(self, user_id: UserId) -> None:
        """Mark a user's email as verified."""
        result = await self._session.execute(select(UserModel).where(UserModel.id == user_id))
        model = result.scalars().first()
        if model is None:
            raise ValueError(f"User with id {user_id} not found.")
        model.email_verified = True
        model.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def update_login_security(
        self,
        user_id: UserId,
        *,
        failed_attempts: int,
        locked_until: datetime | None,
    ) -> None:
        """Update failed attempt counter and optional lockout deadline."""
        result = await self._session.execute(select(UserModel).where(UserModel.id == user_id))
        model = result.scalars().first()
        if model is None:
            raise ValueError(f"User with id {user_id} not found.")
        model.failed_login_attempts = failed_attempts
        model.locked_until = locked_until
        model.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def save_refresh_token(
        self,
        user_id: UserId,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        """Persist a refresh token hash."""
        model = RefreshTokenModel(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
        )
        self._session.add(model)
        await self._session.flush()

    async def find_refresh_token_by_hash(
        self,
        token_hash: str,
    ) -> StoredRefreshToken | None:
        """Look up a refresh token by hash."""
        result = await self._session.execute(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        )
        model = result.scalars().first()
        if model is None:
            return None
        return StoredRefreshToken(
            id=model.id,
            user_id=UserId(model.user_id),
            token_hash=model.token_hash,
            expires_at=_as_utc(model.expires_at),  # type: ignore[arg-type]
            revoked_at=_as_utc(model.revoked_at),
            created_at=_as_utc(model.created_at),  # type: ignore[arg-type]
        )

    async def revoke_refresh_token(self, token_id: uuid.UUID) -> None:
        """Revoke a refresh token row."""
        result = await self._session.execute(
            select(RefreshTokenModel).where(RefreshTokenModel.id == token_id)
        )
        model = result.scalars().first()
        if model is None:
            return
        model.revoked_at = datetime.now(UTC)
        await self._session.flush()

    @staticmethod
    def _verification_to_domain(model: VerificationTokenModel) -> EmailVerificationCode:
        return EmailVerificationCode(
            id=model.id,
            user_id=UserId(model.user_id),
            code_hash=model.code_hash,
            expires_at=_as_utc(model.expires_at),  # type: ignore[arg-type]
            attempt_count=model.attempt_count,
            used_at=_as_utc(model.used_at),
            last_sent_at=_as_utc(model.last_sent_at),
            purpose=model.purpose,
            created_at=_as_utc(model.created_at),  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_domain(model: UserModel) -> User:
        """Convert an ORM model to a domain entity."""
        return User(
            id=UserId(model.id),
            email=model.email,
            hashed_password=model.hashed_password,
            full_name=model.full_name,
            email_verified=model.email_verified,
            is_active=model.is_active,
            failed_login_attempts=model.failed_login_attempts,
            locked_until=_as_utc(model.locked_until),
            created_at=_as_utc(model.created_at),  # type: ignore[arg-type]
            updated_at=_as_utc(model.updated_at),  # type: ignore[arg-type]
        )
