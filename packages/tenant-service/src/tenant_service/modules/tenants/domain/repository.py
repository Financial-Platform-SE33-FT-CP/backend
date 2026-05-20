from __future__ import annotations

from abc import ABC, abstractmethod

from accounting_shared.types import TenantId, UserId

from .entities import CoaAccountRow, Tenant, TenantMemberRow, TenantUser


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
    async def tenant_exists(self, tenant_id: TenantId) -> bool:
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
    async def write_audit_rbac_denied(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
        permission: str,
        reason: str,
        request_id: str | None,
        target_resource: str | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def list_coa_for_tenant(self, tenant_id: TenantId) -> list[CoaAccountRow]:
        ...

    @abstractmethod
    async def remove_user(self, tenant_id: TenantId, user_id: UserId) -> None:
        ...

    @abstractmethod
    async def find_user_id_by_email(self, email: str) -> UserId | None:
        ...

    @abstractmethod
    async def list_tenant_members(self, tenant_id: TenantId) -> list[TenantMemberRow]:
        ...

    @abstractmethod
    async def count_active_owners(self, tenant_id: TenantId) -> int:
        ...

    @abstractmethod
    async def update_membership_role(
        self, tenant_id: TenantId, user_id: UserId, new_role: str
    ) -> bool:
        """Return True if the membership row existed and was updated."""
