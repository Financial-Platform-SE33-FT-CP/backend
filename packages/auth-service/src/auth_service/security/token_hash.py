"""Keyed hashing for opaque tokens (verification + refresh)."""

from __future__ import annotations

import hashlib
import hmac
import uuid


def hash_opaque_token(secret: str, raw_token: str) -> str:
    """Return a deterministic HMAC-SHA256 hex digest for storage and lookup."""
    return hmac.new(
        secret.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_email_verification_code(secret: str, user_id: uuid.UUID, raw_code: str) -> str:
    """HMAC material includes user id so equal codes for different users do not collide."""
    return hash_opaque_token(secret, f"{user_id!s}:{raw_code}")
