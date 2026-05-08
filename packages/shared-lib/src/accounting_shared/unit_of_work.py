"""Unit-of-Work pattern base class."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseUnitOfWork(ABC):
    """Abstract unit of work providing transactional scope.

    Usage::

        async with uow:
            repo = uow.repositories.some_repo
            await repo.add(entity)
            # auto-commits on success, rolls back on exception
    """

    @abstractmethod
    async def __aenter__(self) -> None:
        """Enter the transactional context."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the transactional context.

        Commits on success, rolls back on exception.
        """

    @abstractmethod
    async def commit(self) -> None:
        """Explicitly flush and commit the current transaction."""

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the current transaction."""
