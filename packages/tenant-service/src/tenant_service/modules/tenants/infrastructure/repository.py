from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.types import TenantId, UserId

from ..domain.entities import Tenant, TenantUser
from ..domain.repository import TenantRepository
from .models import TenantModel, TenantUserModel


class SqlAlchemyTenantRepository(TenantRepository):
    """SQLAlchemy implementation of the tenant repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: TenantId) -> Tenant | None:
        stmt = select(TenantModel).where(TenantModel.id == str(tenant_id))
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_domain_tenant(row)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        stmt = select(TenantModel).where(TenantModel.slug == slug)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_domain_tenant(row)

    async def create(self, tenant: Tenant) -> Tenant:
        model = TenantModel(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain_tenant(model)

    async def list_for_user(self, user_id: UserId) -> list[Tenant]:
        stmt = (
            select(TenantModel)
            .join(TenantUserModel, TenantModel.id == TenantUserModel.tenant_id)
            .where(TenantUserModel.user_id == str(user_id))
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain_tenant(r) for r in rows]

    async def add_user(self, tenant_user: TenantUser) -> TenantUser:
        model = TenantUserModel(
            id=tenant_user.id,
            tenant_id=str(tenant_user.tenant_id),
            user_id=str(tenant_user.user_id),
            role=tenant_user.role,
            created_at=tenant_user.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return tenant_user

    async def remove_user(self, tenant_id: TenantId, user_id: UserId) -> None:
        stmt = select(TenantUserModel).where(
            TenantUserModel.tenant_id == str(tenant_id),
            TenantUserModel.user_id == str(user_id),
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def get_user_role(self, tenant_id: TenantId, user_id: UserId) -> str | None:
        stmt = select(TenantUserModel.role).where(
            TenantUserModel.tenant_id == str(tenant_id),
            TenantUserModel.user_id == str(user_id),
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return row

    @staticmethod
    def _to_domain_tenant(model: TenantModel) -> Tenant:
        return Tenant(
            id=TenantId(model.id),
            name=model.name,
            slug=model.slug,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
