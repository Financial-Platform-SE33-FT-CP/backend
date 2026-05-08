"""SQLAlchemy implementation of the UserRepository interface."""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.repository import BaseRepository
from accounting_shared.types import UserId, new_user_id

from auth_service.modules.auth.domain.entities import User, VerificationToken
from auth_service.modules.auth.domain.repository import UserRepository
from auth_service.modules.auth.infrastructure.models import (
    UserModel,
    VerificationTokenModel,
)


class SqlAlchemyUserRepository(BaseRepository, UserRepository):
    """SQLAlchemy-backed user repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        """Retrieve a user by email address."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        model = result.scalars().first()
        return self._to_domain(model) if model else None

    async def get_by_id(self, id: UserId) -> User | None:
        """Retrieve a user by their unique identifier."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == id)
        )
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
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain(model)  # type: ignore[return-value]

    async def update(self, user: User) -> User:
        """Update an existing user."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user.id)
        )
        model = result.scalars().first()
        if model is None:
            raise ValueError(f"User with id {user.id} not found.")

        model.email = user.email
        model.hashed_password = user.hashed_password
        model.full_name = user.full_name
        model.email_verified = user.email_verified
        model.is_active = user.is_active
        model.updated_at = datetime.now(timezone.utc)

        await self._session.flush()
        return self._to_domain(model)  # type: ignore[return-value]

    async def create_verification_token(
        self, user_id: UserId
    ) -> VerificationToken:
        """Create an email verification token for the given user."""
        token_value = secrets.token_urlsafe(32)
        model = VerificationTokenModel(
            user_id=user_id,
            token=token_value,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self._session.add(model)
        await self._session.flush()
        return VerificationToken(
            id=model.id,  # type: ignore[arg-type]
            user_id=UserId(model.user_id),
            token=model.token,
            expires_at=model.expires_at,
            created_at=model.created_at,
        )

    async def get_verification_token(
        self, token: str
    ) -> VerificationToken | None:
        """Retrieve a verification token by its value."""
        result = await self._session.execute(
            select(VerificationTokenModel).where(
                VerificationTokenModel.token == token
            )
        )
        model = result.scalars().first()
        if model is None:
            return None
        return VerificationToken(
            id=model.id,  # type: ignore[arg-type]
            user_id=UserId(model.user_id),
            token=model.token,
            expires_at=model.expires_at,
            created_at=model.created_at,
        )

    async def mark_email_verified(self, user_id: UserId) -> None:
        """Mark a user's email as verified."""
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalars().first()
        if model is None:
            raise ValueError(f"User with id {user_id} not found.")
        model.email_verified = True
        model.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

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
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
