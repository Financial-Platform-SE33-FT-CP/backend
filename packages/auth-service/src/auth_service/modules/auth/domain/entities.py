"""Auth domain entities."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from accounting_shared.types import UserId


@dataclass
class User:
    """Domain entity representing an authenticated user."""

    id: UserId
    email: str
    hashed_password: str
    full_name: str | None = None
    email_verified: bool = False
    is_active: bool = True
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class VerificationToken:
    """Persisted email verification token metadata (no raw token)."""

    id: uuid.UUID
    user_id: UserId
    token_hash: str
    expires_at: datetime
    used_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class StoredRefreshToken:
    """Persisted refresh token metadata (no raw token)."""

    id: uuid.UUID
    user_id: UserId
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
