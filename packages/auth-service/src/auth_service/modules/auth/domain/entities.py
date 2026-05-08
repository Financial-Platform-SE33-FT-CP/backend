"""Auth domain entities."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class VerificationToken:
    """Domain entity representing an email verification token."""

    id: UserId
    user_id: UserId
    token: str
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
