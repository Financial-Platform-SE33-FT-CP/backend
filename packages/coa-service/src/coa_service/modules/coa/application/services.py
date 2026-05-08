from datetime import datetime

from accounting_shared.types import AccountId, TenantId, new_account_id

from coa_service.config import COASettings
from coa_service.modules.coa.application.dto import (
    AccountResponse,
    AccountTreeNode,
    CreateAccountRequest,
    UpdateAccountRequest,
)
from coa_service.modules.coa.domain.entities import Account
from coa_service.modules.coa.domain.exceptions import (
    AccountCodeExistsError,
    AccountNotFoundError,
    CannotDeleteSystemAccountError,
    InvalidAccountTypeError,
)
from coa_service.modules.coa.domain.repository import AccountRepository

ACCOUNT_TYPE_CHOICES = frozenset({"asset", "liability", "equity", "revenue", "expense"})


class COAService:
    """Application service for Chart of Accounts operations."""

    def __init__(self, repository: AccountRepository) -> None:
        self._repository = repository

    async def create_account(
        self, tenant_id: TenantId, request: CreateAccountRequest
    ) -> AccountResponse:
        if request.account_type not in ACCOUNT_TYPE_CHOICES:
            raise InvalidAccountTypeError(request.account_type)

        existing = await self._repository.get_by_code(request.code, tenant_id)
        if existing:
            raise AccountCodeExistsError(request.code)

        parent_id: AccountId | None = None
        if request.parent_code:
            parent = await self._repository.get_by_code(request.parent_code, tenant_id)
            if not parent:
                raise AccountNotFoundError(f"parent_code={request.parent_code}")
            parent_id = parent.id

        now = datetime.utcnow()
        account = Account(
            id=new_account_id(),
            tenant_id=tenant_id,
            code=request.code,
            name=request.name,
            account_type=request.account_type,
            parent_id=parent_id,
            is_active=True,
            is_system=False,
            description=request.description or "",
            created_at=now,
            updated_at=now,
        )

        created = await self._repository.create(account)
        return AccountResponse.model_validate(created)

    async def update_account(
        self, account_id: AccountId, tenant_id: TenantId, request: UpdateAccountRequest
    ) -> AccountResponse:
        account = await self._repository.get_by_id(account_id, tenant_id)
        if not account:
            raise AccountNotFoundError(str(account_id))

        if request.name is not None:
            account.name = request.name
        if request.description is not None:
            account.description = request.description
        if request.is_active is not None:
            if not request.is_active and account.is_system:
                raise CannotDeleteSystemAccountError(str(account_id))
            account.is_active = request.is_active

        account.updated_at = datetime.utcnow()
        updated = await self._repository.update(account)
        return AccountResponse.model_validate(updated)

    async def list_accounts(self, tenant_id: TenantId) -> list[AccountResponse]:
        accounts = await self._repository.list_by_tenant(tenant_id)
        return [AccountResponse.model_validate(a) for a in accounts]

    async def get_account_tree(self, tenant_id: TenantId) -> list[AccountTreeNode]:
        accounts = await self._repository.get_tree(tenant_id)

        children_map: dict[AccountId | None, list[Account]] = {}
        for a in accounts:
            pid = a.parent_id
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(a)

        def build_node(a: Account) -> AccountTreeNode:
            return AccountTreeNode(
                id=str(a.id),
                code=a.code,
                name=a.name,
                account_type=a.account_type,
                children=[build_node(c) for c in children_map.get(a.id, [])],
            )

        return [build_node(a) for a in children_map.get(None, [])]

    async def disable_account(
        self, account_id: AccountId, tenant_id: TenantId
    ) -> AccountResponse:
        account = await self._repository.get_by_id(account_id, tenant_id)
        if not account:
            raise AccountNotFoundError(str(account_id))
        if account.is_system:
            raise CannotDeleteSystemAccountError(str(account_id))

        account.is_active = False
        account.updated_at = datetime.utcnow()
        updated = await self._repository.update(account)
        return AccountResponse.model_validate(updated)

    async def seed_default_coa(
        self, tenant_id: TenantId, settings: COASettings
    ) -> list[AccountResponse]:
        created: list[AccountResponse] = []
        for item in settings.default_coa_accounts:
            existing = await self._repository.get_by_code(item["code"], tenant_id)
            if existing:
                continue
            now = datetime.utcnow()
            account = Account(
                id=new_account_id(),
                tenant_id=tenant_id,
                code=item["code"],
                name=item["name"],
                account_type=item["type"],
                parent_id=None,
                is_active=True,
                is_system=True,
                description=item.get("description", ""),
                created_at=now,
                updated_at=now,
            )
            created_account = await self._repository.create(account)
            created.append(AccountResponse.model_validate(created_account))
        return created
