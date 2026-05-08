from abc import ABC, abstractmethod

from accounting_shared.types import AccountId, TenantId

from coa_service.modules.coa.domain.entities import Account


class AccountRepository(ABC):
    """Repository interface for Account aggregate root."""

    @abstractmethod
    async def get_by_id(self, account_id: AccountId, tenant_id: TenantId) -> Account | None:
        ...

    @abstractmethod
    async def get_by_code(self, code: str, tenant_id: TenantId) -> Account | None:
        ...

    @abstractmethod
    async def list_by_tenant(self, tenant_id: TenantId) -> list[Account]:
        ...

    @abstractmethod
    async def list_children(self, parent_id: AccountId) -> list[Account]:
        ...

    @abstractmethod
    async def create(self, account: Account) -> Account:
        ...

    @abstractmethod
    async def update(self, account: Account) -> Account:
        ...

    @abstractmethod
    async def get_tree(self, tenant_id: TenantId) -> list[Account]:
        ...
