"""Unit tests for accounting_shared.unit_of_work module."""

from __future__ import annotations

import pytest

from accounting_shared.unit_of_work import BaseUnitOfWork


class TestBaseUnitOfWork:
    """Tests for BaseUnitOfWork abstract class."""

    def test_base_unit_of_work_is_abstract(self):
        """BaseUnitOfWork should be abstract and cannot be instantiated."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseUnitOfWork()

    def test_base_unit_of_work_has_abstract_methods(self):
        """BaseUnitOfWork should have abstract methods."""
        assert hasattr(BaseUnitOfWork, "__aenter__")
        assert hasattr(BaseUnitOfWork, "__aexit__")
        assert hasattr(BaseUnitOfWork, "commit")
        assert hasattr(BaseUnitOfWork, "rollback")

    def test_concrete_subclass_must_implement_all_methods(self):
        """Concrete subclass must implement all abstract methods."""

        class IncompleteUnitOfWork(BaseUnitOfWork):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteUnitOfWork()

    def test_concrete_subclass_with_all_methods(self):
        """Concrete subclass with all methods can be instantiated."""

        class CompleteUnitOfWork(BaseUnitOfWork):
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def commit(self):
                pass

            async def rollback(self):
                pass

        # Should not raise
        uow = CompleteUnitOfWork()
        assert uow is not None

    @pytest.mark.asyncio
    async def test_concrete_subclass_context_manager(self):
        """Concrete subclass should work as an async context manager."""

        class TestUnitOfWork(BaseUnitOfWork):
            def __init__(self):
                self.committed = False
                self.rolled_back = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                if exc_type is not None:
                    await self.rollback()
                else:
                    await self.commit()

            async def commit(self):
                self.committed = True

            async def rollback(self):
                self.rolled_back = True

        uow = TestUnitOfWork()

        # Test successful context
        async with uow:
            pass

        assert uow.committed is True
        assert uow.rolled_back is False

        # Reset
        uow.committed = False
        uow.rolled_back = False

        # Test context with exception
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("test error")

        assert uow.committed is False
        assert uow.rolled_back is True
