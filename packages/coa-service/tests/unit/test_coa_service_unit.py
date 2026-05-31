from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from accounting_shared.types import AccountId, TenantId

from coa_service.modules.coa.application.dto import CreateAccountRequest, UpdateAccountRequest
from coa_service.modules.coa.application.services import COAService
from coa_service.modules.coa.domain.entities import Account
from coa_service.modules.coa.domain.exceptions import (
    AccountCodeExistsError,
    CannotDeleteSystemAccountError,
    InvalidAccountTypeError,
)
from coa_service.modules.coa.domain.repository import AccountRepository


def new_tenant_id() -> TenantId:
    return TenantId(uuid.uuid4())


def new_id() -> AccountId:
    return AccountId(uuid.uuid4())


def make_account(
    tenant_id: TenantId,
    *,
    code: str = "1000",
    name: str = "Cash",
    account_type: str = "asset",
    parent_id: AccountId | None = None,
    is_active: bool = True,
    is_system: bool = False,
) -> Account:
    now = datetime(2026, 1, 1)
    return Account(
        id=new_id(),
        tenant_id=tenant_id,
        code=code,
        name=name,
        account_type=account_type,
        parent_id=parent_id,
        is_active=is_active,
        is_system=is_system,
        description="",
        created_at=now,
        updated_at=now,
    )


class FakeAccountRepository(AccountRepository):
    def __init__(self) -> None:
        self.accounts: dict[AccountId, Account] = {}

    def add(self, account: Account) -> Account:
        self.accounts[account.id] = account
        return account

    async def get_by_id(self, account_id: AccountId, tenant_id: TenantId) -> Account | None:
        account = self.accounts.get(account_id)
        if account and account.tenant_id == tenant_id:
            return account
        return None

    async def get_by_code(self, code: str, tenant_id: TenantId) -> Account | None:
        for account in self.accounts.values():
            if account.code == code and account.tenant_id == tenant_id:
                return account
        return None

    async def list_by_tenant(self, tenant_id: TenantId) -> list[Account]:
        return sorted(
            [account for account in self.accounts.values() if account.tenant_id == tenant_id],
            key=lambda account: account.code,
        )

    async def list_children(self, parent_id: AccountId) -> list[Account]:
        return sorted(
            [account for account in self.accounts.values() if account.parent_id == parent_id],
            key=lambda account: account.code,
        )

    async def create(self, account: Account) -> Account:
        self.accounts[account.id] = account
        return account

    async def update(self, account: Account) -> Account:
        self.accounts[account.id] = account
        return account

    async def get_tree(self, tenant_id: TenantId) -> list[Account]:
        return await self.list_by_tenant(tenant_id)


@pytest.mark.asyncio
async def test_create_account_success() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    response = await service.create_account(
        tenant_id,
        CreateAccountRequest(
            code="1010",
            name="Bank Account",
            account_type="asset",
            description="Main bank account",
        ),
    )

    assert response.code == "1010"
    assert response.name == "Bank Account"
    assert response.account_type == "asset"
    assert response.tenant_id == str(tenant_id)
    assert response.is_active is True
    assert response.is_system is False

    stored = await repo.get_by_code("1010", tenant_id)
    assert stored is not None


@pytest.mark.asyncio
async def test_create_account_duplicate_code_raises() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    repo.add(make_account(tenant_id, code="1000", name="Cash"))

    with pytest.raises(AccountCodeExistsError):
        await service.create_account(
            tenant_id,
            CreateAccountRequest(
                code="1000",
                name="Duplicate Cash",
                account_type="asset",
            ),
        )


@pytest.mark.asyncio
async def test_create_account_invalid_type_raises() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    with pytest.raises(InvalidAccountTypeError):
        await service.create_account(
            tenant_id,
            CreateAccountRequest(
                code="9999",
                name="Invalid Type Account",
                account_type="invalid_type",
            ),
        )


@pytest.mark.asyncio
async def test_create_account_with_parent_code() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    parent = repo.add(make_account(tenant_id, code="1000", name="Assets"))

    response = await service.create_account(
        tenant_id,
        CreateAccountRequest(
            code="1010",
            name="Cash",
            account_type="asset",
            parent_code="1000",
        ),
    )

    assert response.parent_id == str(parent.id)


@pytest.mark.asyncio
async def test_update_account_changes_name_description_and_status() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    account = repo.add(make_account(tenant_id, code="5000", name="Old Expense"))

    response = await service.update_account(
        account.id,
        tenant_id,
        UpdateAccountRequest(
            name="Updated Expense",
            description="Updated description",
            is_active=False,
        ),
    )

    assert response.name == "Updated Expense"
    assert response.description == "Updated description"
    assert response.is_active is False


@pytest.mark.asyncio
async def test_update_account_cannot_disable_system_account() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    account = repo.add(
        make_account(
            tenant_id,
            code="1000",
            name="System Cash",
            is_system=True,
        )
    )

    with pytest.raises(CannotDeleteSystemAccountError):
        await service.update_account(
            account.id,
            tenant_id,
            UpdateAccountRequest(is_active=False),
        )


@pytest.mark.asyncio
async def test_disable_account_success() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    account = repo.add(make_account(tenant_id, code="6000", name="Office Expense"))

    response = await service.disable_account(account.id, tenant_id)

    assert response.is_active is False


@pytest.mark.asyncio
async def test_disable_system_account_raises() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    account = repo.add(
        make_account(
            tenant_id,
            code="4000",
            name="System Revenue",
            account_type="revenue",
            is_system=True,
        )
    )

    with pytest.raises(CannotDeleteSystemAccountError):
        await service.disable_account(account.id, tenant_id)


@pytest.mark.asyncio
async def test_list_accounts_returns_only_current_tenant_accounts() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)

    tenant_a = new_tenant_id()
    tenant_b = new_tenant_id()

    repo.add(make_account(tenant_a, code="1000", name="Cash"))
    repo.add(make_account(tenant_a, code="2000", name="Payable", account_type="liability"))
    repo.add(make_account(tenant_b, code="9999", name="Other Tenant Account"))

    response = await service.list_accounts(tenant_a)

    assert [account.code for account in response] == ["1000", "2000"]


@pytest.mark.asyncio
async def test_get_account_tree_returns_parent_child_structure() -> None:
    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    parent = repo.add(make_account(tenant_id, code="1000", name="Assets"))
    repo.add(make_account(tenant_id, code="1010", name="Cash", parent_id=parent.id))
    repo.add(make_account(tenant_id, code="1020", name="Bank", parent_id=parent.id))

    tree = await service.get_account_tree(tenant_id)

    assert len(tree) == 1
    assert tree[0].code == "1000"
    assert [child.code for child in tree[0].children] == ["1010", "1020"]


@pytest.mark.asyncio
async def test_seed_default_coa_skips_existing_accounts() -> None:
    class DummySettings:
        default_coa_accounts = [
            {"code": "1000", "name": "Cash", "type": "asset"},
            {"code": "2000", "name": "Accounts Payable", "type": "liability"},
        ]

    repo = FakeAccountRepository()
    service = COAService(repo)
    tenant_id = new_tenant_id()

    repo.add(make_account(tenant_id, code="1000", name="Existing Cash"))

    created = await service.seed_default_coa(tenant_id, DummySettings())  # type: ignore[arg-type]
    all_accounts = await service.list_accounts(tenant_id)

    assert [account.code for account in created] == ["2000"]
    assert [account.code for account in all_accounts] == ["1000", "2000"]
