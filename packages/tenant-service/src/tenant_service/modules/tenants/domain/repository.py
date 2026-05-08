from __future__ import annotations

from abc import ABC, abstractmethod

from accounting_shared.types import TenantId, UserId

from .entities import Tenant, TenantUser


class TenantRepository(ABC):
    """Abstract repository for tenant persistence."""

    @abstractmethod
    async def get_by_id(self, tenant_id: TenantId) -> Tenant | None:
        ...

    @abstractmethod
    async def get_by_slug(self, slug: str) -> Tenant | None:
        ...

    @abstractmethod
    async def create(self, tenant: Tenant) -> Tenant:
        ...

    @abstractmethod
    async def list_for_user(self, user_id: UserId) -> list[Tenant]:
        ...

    @abstractmethod
    async def add_user(self, tenant_user: TenantUser) -> TenantUser:
        ...

    @abstractmethod
    async def remove_user(self, tenant_id: TenantId, user_id: UserId) -> None:
        ...

    @abstractmethod
    async def get_user_role(self, tenant_id: TenantId, user_id: UserId) -> str | None:
        ...
