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
class EmailVerificationCode:
    """Persisted email verification code metadata (only hash stored; column is token_hash in DB)."""

    id: uuid.UUID
    user_id: UserId
    code_hash: str
    expires_at: datetime
    attempt_count: int
    used_at: datetime | None = None
    last_sent_at: datetime | None = None
    purpose: str = "email_verification"
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
