"""Generic repository pattern base class."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.types import TenantId

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """Abstract base repository providing CRUD conventions.

    Concrete subclasses must provide a *session* and implement the abstract
    methods below.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        """Return the underlying async session."""
        return self._session

    @property
    def current_tenant_id(self) -> TenantId | None:
        """Return the tenant id associated with the current request context.

        Subclasses may override this to wire in a different tenant resolution
        strategy.
        """
        from accounting_shared.middleware.tenant_context import get_current_tenant_id

        tid = get_current_tenant_id()
        if tid is None:
            return None
        return TenantId(uuid.UUID(str(tid)))

    @abstractmethod
    async def get_by_id(self, id: uuid.UUID) -> T | None:  # noqa: A002
        """Retrieve an entity by its primary key."""

    @abstractmethod
    async def add(self, entity: T) -> T:
        """Persist a new entity."""

    @abstractmethod
    async def update(self, entity: T) -> T:
        """Persist changes to an existing entity."""

    @abstractmethod
    async def delete(self, entity: T) -> None:
        """Remove an entity from persistence."""
