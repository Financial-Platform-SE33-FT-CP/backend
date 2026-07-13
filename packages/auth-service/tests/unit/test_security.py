"""Unit tests for security hashing utilities."""
from __future__ import annotations

import uuid


from auth_service.security.token_hash import (
    hash_email_verification_code,
    hash_opaque_token,
)


class TestHashOpaqueToken:
    """Tests for hash_opaque_token — deterministic HMAC-SHA256."""

    def test_consistent_for_same_input(self) -> None:
        h1 = hash_opaque_token("my-secret", "raw-token-value")
        h2 = hash_opaque_token("my-secret", "raw-token-value")
        assert h1 == h2

    def test_different_for_different_secret(self) -> None:
        h1 = hash_opaque_token("secret-a", "same-token")
        h2 = hash_opaque_token("secret-b", "same-token")
        assert h1 != h2

    def test_different_for_different_token(self) -> None:
        h1 = hash_opaque_token("secret", "token-1")
        h2 = hash_opaque_token("secret", "token-2")
        assert h1 != h2

    def test_output_is_hex_string(self) -> None:
        h = hash_opaque_token("secret", "token")
        assert isinstance(h, str)
        assert len(h) == 64
        int(h, 16)  # should not raise

    def test_empty_token_hashes_deterministically(self) -> None:
        h1 = hash_opaque_token("secret", "")
        h2 = hash_opaque_token("secret", "")
        assert h1 == h2

    def test_empty_secret_still_produces_output(self) -> None:
        h = hash_opaque_token("", "token")
        assert len(h) == 64


class TestHashEmailVerificationCode:
    """Tests for hash_email_verification_code — scoped HMAC-SHA256."""

    def test_consistent_for_same_input(self) -> None:
        uid = uuid.uuid4()
        h1 = hash_email_verification_code("secret", uid, "123456")
        h2 = hash_email_verification_code("secret", uid, "123456")
        assert h1 == h2

    def test_different_for_different_secret(self) -> None:
        uid = uuid.uuid4()
        h1 = hash_email_verification_code("secret-a", uid, "123456")
        h2 = hash_email_verification_code("secret-b", uid, "123456")
        assert h1 != h2

    def test_different_for_different_user(self) -> None:
        h1 = hash_email_verification_code("secret", uuid.uuid4(), "123456")
        h2 = hash_email_verification_code("secret", uuid.uuid4(), "123456")
        assert h1 != h2

    def test_different_for_different_code(self) -> None:
        uid = uuid.uuid4()
        h1 = hash_email_verification_code("secret", uid, "111111")
        h2 = hash_email_verification_code("secret", uid, "222222")
        assert h1 != h2

    def test_output_is_hex_string(self) -> None:
        uid = uuid.uuid4()
        h = hash_email_verification_code("secret", uid, "123456")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_matches_hash_opaque_token_behavior(self) -> None:
        """hash_email_verification_code delegates to hash_opaque_token."""
        uid = uuid.uuid4()
        h1 = hash_email_verification_code("secret", uid, "123456")
        h2 = hash_opaque_token("secret", f"{uid!s}:123456")
        assert h1 == h2
