"""Unit tests for accounting_shared.types module."""

from __future__ import annotations

import uuid

from accounting_shared.types import (
    AccountId,
    JournalEntryId,
    PositiveAmount,
    TenantId,
    UserId,
    new_account_id,
    new_tenant_id,
    new_user_id,
)


class TestTypeAliases:
    """Tests for type aliases."""

    def test_tenant_id_is_uuid(self):
        """TenantId should be a UUID instance."""
        tenant_id = TenantId(uuid.uuid4())
        assert isinstance(tenant_id, uuid.UUID)

    def test_user_id_is_uuid(self):
        """UserId should be a UUID instance."""
        user_id = UserId(uuid.uuid4())
        assert isinstance(user_id, uuid.UUID)

    def test_account_id_is_uuid(self):
        """AccountId should be a UUID instance."""
        account_id = AccountId(uuid.uuid4())
        assert isinstance(account_id, uuid.UUID)

    def test_journal_entry_id_is_uuid(self):
        """JournalEntryId should be a UUID instance."""
        journal_entry_id = JournalEntryId(uuid.uuid4())
        assert isinstance(journal_entry_id, uuid.UUID)


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_new_tenant_id_returns_uuid(self):
        """new_tenant_id should return a UUID instance."""
        tenant_id = new_tenant_id()
        assert isinstance(tenant_id, uuid.UUID)

    def test_new_tenant_id_returns_unique_values(self):
        """new_tenant_id should return unique values."""
        ids = [new_tenant_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_new_user_id_returns_uuid(self):
        """new_user_id should return a UUID instance."""
        user_id = new_user_id()
        assert isinstance(user_id, uuid.UUID)

    def test_new_user_id_returns_unique_values(self):
        """new_user_id should return unique values."""
        ids = [new_user_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_new_account_id_returns_uuid(self):
        """new_account_id should return a UUID instance."""
        account_id = new_account_id()
        assert isinstance(account_id, uuid.UUID)

    def test_new_account_id_returns_unique_values(self):
        """new_account_id should return unique values."""
        ids = [new_account_id() for _ in range(100)]
        assert len(set(ids)) == 100


class TestPositiveAmount:
    """Tests for PositiveAmount type annotation."""

    def test_positive_amount_is_float_annotation(self):
        """PositiveAmount should be a float annotation."""
        # PositiveAmount is an Annotated type, not a runtime checkable type
        # We can check its metadata
        assert PositiveAmount.__origin__ is float  # type: ignore[attr-defined]

    def test_positive_amount_has_metadata(self):
        """PositiveAmount should have metadata string."""
        assert PositiveAmount.__metadata__ == ("Value must be > 0",)  # type: ignore[attr-defined]
