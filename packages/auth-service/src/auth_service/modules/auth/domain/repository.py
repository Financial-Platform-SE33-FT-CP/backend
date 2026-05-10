"""User repository interface (abstract)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from accounting_shared.types import UserId

from auth_service.modules.auth.domain.entities import (
    EmailVerificationCode,
    StoredRefreshToken,
    User,
)


class UserRepository(ABC):
    """Abstract repository for user persistence operations."""

    @abstractmethod
    async def commit(self) -> None:
        """Persist pending changes when the request ends with a domain error."""
        ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        """Retrieve a user by email address."""
        ...

    @abstractmethod
    async def get_by_id(self, id: UserId) -> User | None:  # noqa: A002
        """Retrieve a user by their unique identifier."""
        ...

    @abstractmethod
    async def add(self, user: User) -> User:
        """Persist a new user."""
        ...

    @abstractmethod
    async def update(self, user: User) -> User:
        """Update an existing user."""
        ...

    @abstractmethod
    async def delete(self, user: User) -> None:
        """Remove a user — optional for future admin flows."""
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def find_latest_unused_verification_code_for_user(
        self,
        user_id: UserId,
    ) -> EmailVerificationCode | None:
        """Return the newest unused verification code row for this user."""
        ...

    @abstractmethod
    async def find_latest_verification_code_row_for_user(
        self,
        user_id: UserId,
    ) -> EmailVerificationCode | None:
        """Return the newest verification row (used or not) for cooldown checks."""
        ...

    @abstractmethod
    async def increment_verification_code_attempts(self, code_id: uuid.UUID) -> None:
        """Increment wrong-code attempt counter."""
        ...

    @abstractmethod
    async def mark_verification_code_used(self, code_id: uuid.UUID) -> None:
        """Mark a verification code as consumed."""
        ...

    @abstractmethod
    async def mark_all_pending_verification_codes_used_for_user(
        self,
        user_id: UserId,
        *,
        except_code_id: uuid.UUID | None = None,
    ) -> None:
        """Invalidate other pending codes (e.g. after success or before new resend)."""
        ...

    @abstractmethod
    async def mark_email_verified(self, user_id: UserId) -> None:
        """Mark a user's email as verified."""
        ...

    @abstractmethod
    async def update_login_security(
        self,
        user_id: UserId,
        *,
        failed_attempts: int,
        locked_until: datetime | None,
    ) -> None:
        """Update failed attempt counter and optional lockout deadline."""
        ...

    @abstractmethod
    async def save_refresh_token(
        self,
        user_id: UserId,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        """Persist a refresh token hash."""
        ...

    @abstractmethod
    async def find_refresh_token_by_hash(
        self,
        token_hash: str,
    ) -> StoredRefreshToken | None:
        """Look up a refresh token by hash."""
        ...

    @abstractmethod
    async def revoke_refresh_token(self, token_id: uuid.UUID) -> None:
        """Revoke a refresh token row."""
        ...
