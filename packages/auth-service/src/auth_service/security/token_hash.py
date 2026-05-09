"""Keyed hashing for opaque tokens (verification + refresh)."""

from __future__ import annotations

import hashlib
import hmac


def hash_opaque_token(secret: str, raw_token: str) -> str:
    """Return a deterministic HMAC-SHA256 hex digest for storage and lookup."""
    return hmac.new(
        secret.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
