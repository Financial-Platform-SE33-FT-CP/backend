from __future__ import annotations

from abc import ABC, abstractmethod

from accounting_shared.types import TenantId, UserId

from .entities import CoaAccountRow, Tenant, TenantUser


class TenantRepository(ABC):
    """Abstract repository for tenant persistence."""

    @abstractmethod
    async def create(self, tenant: Tenant) -> Tenant:
        ...

    @abstractmethod
    async def add_user(self, tenant_user: TenantUser) -> TenantUser:
        ...

    @abstractmethod
    async def get_by_id(self, tenant_id: TenantId) -> Tenant | None:
        ...

    @abstractmethod
    async def get_for_active_member(self, tenant_id: TenantId, user_id: UserId) -> Tenant | None:
        ...

    @abstractmethod
    async def list_for_active_user(self, user_id: UserId) -> list[tuple[Tenant, str]]:
        """Return (tenant, role) for active memberships."""

    @abstractmethod
    async def get_user_role(self, tenant_id: TenantId, user_id: UserId) -> str | None:
        """Role when membership is active; otherwise ``None``."""

    @abstractmethod
    async def seed_default_coa(self, tenant_id: TenantId) -> None:
        ...

    @abstractmethod
    async def write_audit_tenant_created(self, *, tenant_id: TenantId, user_id: UserId) -> None:
        ...

    @abstractmethod
    async def list_coa_for_tenant(self, tenant_id: TenantId) -> list[CoaAccountRow]:
        ...

    @abstractmethod
    async def remove_user(self, tenant_id: TenantId, user_id: UserId) -> None:
        ...
