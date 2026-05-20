from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.types import AccountId, TenantId
from coa_service.modules.coa.domain.entities import Account
from coa_service.modules.coa.domain.repository import AccountRepository
from coa_service.modules.coa.infrastructure.models import AccountModel, AccountType


class SqlAlchemyAccountRepository(AccountRepository):
    """SQLAlchemy implementation of AccountRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(self, account_id: AccountId, tenant_id: TenantId) -> Account | None:
        stmt = select(AccountModel).where(
            AccountModel.id == account_id,
            AccountModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_code(self, code: str, tenant_id: TenantId) -> Account | None:
        stmt = select(AccountModel).where(
            AccountModel.code == code,
            AccountModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_tenant(self, tenant_id: TenantId) -> list[Account]:
        stmt = (
            select(AccountModel)
            .where(AccountModel.tenant_id == tenant_id)
            .order_by(AccountModel.code)
        )
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_children(self, parent_id: AccountId) -> list[Account]:
        stmt = (
            select(AccountModel)
            .where(AccountModel.parent_id == parent_id)
            .order_by(AccountModel.code)
        )
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_tree(self, tenant_id: TenantId) -> list[Account]:
        stmt = (
            select(AccountModel)
            .where(AccountModel.tenant_id == tenant_id)
            .order_by(AccountModel.code)
        )
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(self, account: Account) -> Account:
        model = self._to_model(account)
        self._session.add(model)
        await self._session.flush()
        return account

    async def update(self, account: Account) -> Account:
        model = await self._session.get(AccountModel, account.id)
        if model is not None:
            model.code = account.code
            model.name = account.name
            model.account_type = AccountType(account.account_type)
            model.parent_id = account.parent_id
            model.is_active = account.is_active
            model.is_system_default = account.is_system
            model.updated_at = account.updated_at
        return account

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entity(model: AccountModel) -> Account:
        return Account(
            id=model.id,
            tenant_id=model.tenant_id,
            code=model.code,
            name=model.name,
            account_type=model.account_type.value,
            parent_id=model.parent_id,
            is_active=model.is_active,
            is_system=model.is_system_default,
            description="",
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_model(entity: Account) -> AccountModel:
        return AccountModel(
            id=entity.id,
            tenant_id=entity.tenant_id,
            code=entity.code,
            name=entity.name,
            account_type=AccountType(entity.account_type),
            parent_id=entity.parent_id,
            is_active=entity.is_active,
            is_system_default=entity.is_system,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
