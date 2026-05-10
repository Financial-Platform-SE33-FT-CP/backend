from __future__ import annotations

import uuid
from datetime import UTC, datetime

from accounting_shared.types import TenantId, UserId
from audit_service.modules.audit.infrastructure.models import AuditLogModel
from coa_service.modules.coa.infrastructure.models import AccountModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.default_sme_coa import DEFAULT_SME_COA_SEED
from ..domain.entities import CoaAccountRow, Tenant, TenantUser
from ..domain.repository import TenantRepository
from .models import TenantModel, TenantUserModel


class SqlAlchemyTenantRepository(TenantRepository):
    """SQLAlchemy implementation of the tenant repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: TenantId) -> Tenant | None:
        stmt = select(TenantModel).where(TenantModel.id == tenant_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_domain_tenant(row)

    async def get_for_active_member(self, tenant_id: TenantId, user_id: UserId) -> Tenant | None:
        stmt = (
            select(TenantModel)
            .join(TenantUserModel, TenantModel.id == TenantUserModel.tenant_id)
            .where(
                TenantModel.id == tenant_id,
                TenantUserModel.user_id == user_id,
                TenantUserModel.status == "active",
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_domain_tenant(row)

    async def list_for_active_user(self, user_id: UserId) -> list[tuple[Tenant, str]]:
        stmt = (
            select(TenantModel, TenantUserModel.role)
            .join(TenantUserModel, TenantModel.id == TenantUserModel.tenant_id)
            .where(TenantUserModel.user_id == user_id, TenantUserModel.status == "active")
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        return [(self._to_domain_tenant(t), role) for t, role in rows]

    async def create(self, tenant: Tenant) -> Tenant:
        model = TenantModel(
            id=tenant.id,
            name=tenant.name,
            uen=tenant.uen,
            base_currency=tenant.base_currency,
            gst_registered=tenant.gst_registered,
            financial_year_start_month=tenant.financial_year_start_month,
            financial_year_start_day=tenant.financial_year_start_day,
            status=tenant.status,
            created_by_user_id=tenant.created_by_user_id,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return self._to_domain_tenant(model)

    async def add_user(self, tenant_user: TenantUser) -> TenantUser:
        model = TenantUserModel(
            id=uuid.UUID(tenant_user.id),
            tenant_id=tenant_user.tenant_id,
            user_id=tenant_user.user_id,
            role=tenant_user.role,
            status=tenant_user.status,
            created_at=tenant_user.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return tenant_user

    async def remove_user(self, tenant_id: TenantId, user_id: UserId) -> None:
        stmt = select(TenantUserModel).where(
            TenantUserModel.tenant_id == tenant_id,
            TenantUserModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def get_user_role(self, tenant_id: TenantId, user_id: UserId) -> str | None:
        stmt = select(TenantUserModel.role).where(
            TenantUserModel.tenant_id == tenant_id,
            TenantUserModel.user_id == user_id,
            TenantUserModel.status == "active",
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return row

    async def seed_default_coa(self, tenant_id: TenantId) -> None:
        now = datetime.now(UTC)
        for code, name, acc_type in DEFAULT_SME_COA_SEED:
            row = AccountModel(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                code=code,
                name=name,
                account_type=acc_type,
                parent_id=None,
                is_active=True,
                is_system_default=True,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        await self._session.flush()

    async def write_audit_tenant_created(self, *, tenant_id: TenantId, user_id: UserId) -> None:
        log = AuditLogModel(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            action="TENANT_CREATED",
            entity_type="tenant",
            entity_id=str(tenant_id),
            changes=None,
        )
        self._session.add(log)
        await self._session.flush()

    async def list_coa_for_tenant(self, tenant_id: TenantId) -> list[CoaAccountRow]:
        stmt = (
            select(AccountModel)
            .where(AccountModel.tenant_id == tenant_id)
            .order_by(AccountModel.code)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [
            CoaAccountRow(
                id=str(m.id),
                tenant_id=str(m.tenant_id),
                code=m.code,
                name=m.name,
                account_type=m.account_type.value,
                parent_id=str(m.parent_id) if m.parent_id else None,
                is_active=m.is_active,
                is_system_default=m.is_system_default,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in models
        ]

    @staticmethod
    def _to_domain_tenant(model: TenantModel) -> Tenant:
        return Tenant(
            id=TenantId(model.id),
            name=model.name,
            uen=model.uen,
            base_currency=model.base_currency,
            gst_registered=model.gst_registered,
            financial_year_start_month=model.financial_year_start_month,
            financial_year_start_day=model.financial_year_start_day,
            status=model.status,
            created_by_user_id=UserId(model.created_by_user_id),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
