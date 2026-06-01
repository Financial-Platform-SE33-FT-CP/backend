"""Unit tests for accounting_shared.repository module."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.repository import BaseRepository


class TestBaseRepository:
    """Tests for BaseRepository abstract class."""

    def test_base_repository_is_abstract(self):
        """BaseRepository should be abstract and cannot be instantiated."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseRepository(None)  # type: ignore[arg-type]

    def test_base_repository_has_abstract_methods(self):
        """BaseRepository should have abstract methods."""
        assert hasattr(BaseRepository, "get_by_id")
        assert hasattr(BaseRepository, "add")
        assert hasattr(BaseRepository, "update")
        assert hasattr(BaseRepository, "delete")

    def test_concrete_subclass_must_implement_all_methods(self):
        """Concrete subclass must implement all abstract methods."""

        class IncompleteRepository(BaseRepository[dict]):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteRepository(None)  # type: ignore[arg-type]

    def test_concrete_subclass_with_all_methods(self):
        """Concrete subclass with all methods can be instantiated."""

        class CompleteRepository(BaseRepository[dict]):
            async def get_by_id(self, id: uuid.UUID) -> dict | None:
                return None

            async def add(self, entity: dict) -> dict:
                return entity

            async def update(self, entity: dict) -> dict:
                return entity

            async def delete(self, entity: dict) -> None:
                pass

        # Should not raise
        repo = CompleteRepository(None)  # type: ignore[arg-type]
        assert repo is not None

    def test_session_property(self):
        """BaseRepository should have a session property."""

        class TestRepository(BaseRepository[dict]):
            async def get_by_id(self, id: uuid.UUID) -> dict | None:
                return None

            async def add(self, entity: dict) -> dict:
                return entity

            async def update(self, entity: dict) -> dict:
                return entity

            async def delete(self, entity: dict) -> None:
                pass

        mock_session = AsyncSession.__new__(AsyncSession)
        repo = TestRepository(mock_session)
        assert repo.session is mock_session

    def test_current_tenant_id_property(self):
        """BaseRepository should have a current_tenant_id property."""

        class TestRepository(BaseRepository[dict]):
            async def get_by_id(self, id: uuid.UUID) -> dict | None:
                return None

            async def add(self, entity: dict) -> dict:
                return entity

            async def update(self, entity: dict) -> dict:
                return entity

            async def delete(self, entity: dict) -> None:
                pass

        repo = TestRepository(None)  # type: ignore[arg-type]
        # By default, should return None (no tenant context set)
        assert repo.current_tenant_id is None

    def test_current_tenant_id_with_context(self):
        """BaseRepository.current_tenant_id should return tenant from context."""
        from accounting_shared.middleware.tenant_context import set_current_tenant_id

        class TestRepository(BaseRepository[dict]):
            async def get_by_id(self, id: uuid.UUID) -> dict | None:
                return None

            async def add(self, entity: dict) -> dict:
                return entity

            async def update(self, entity: dict) -> dict:
                return entity

            async def delete(self, entity: dict) -> None:
                pass

        tenant_id = uuid.uuid4()
        set_current_tenant_id(tenant_id)

        repo = TestRepository(None)  # type: ignore[arg-type]
        assert repo.current_tenant_id == tenant_id
