from __future__ import annotations

import uuid
from datetime import UTC, datetime

from accounting_shared.exceptions import ValidationError
from accounting_shared.types import TenantId, UserId, new_tenant_id

from ..domain.entities import Tenant, TenantUser
from ..domain.exceptions import (
    InsufficientPermissionError,
    TenantNotFoundError,
    UserAlreadyMemberError,
)
from ..domain.repository import TenantRepository
from .dto import (
    AddUserRequest,
    CoaAccountResponse,
    CreateTenantRequest,
    TenantListItemResponse,
    TenantSummaryResponse,
    TenantUserResponse,
)

SUPPORTED_CURRENCIES = frozenset({"SGD", "USD", "EUR", "GBP", "AUD"})


class TenantService:
    """Application service for tenant management."""

    def __init__(self, repository: TenantRepository, settings: object) -> None:
        self._repository = repository
        self._settings = settings

    async def create_tenant(
        self, dto: CreateTenantRequest, owner_user_id: UserId
    ) -> TenantSummaryResponse:
        if dto.base_currency.upper() not in SUPPORTED_CURRENCIES:
            raise ValidationError("Unsupported base currency.")

        now = datetime.now(UTC)
        tenant_id = new_tenant_id()
        tenant = Tenant(
            id=tenant_id,
            name=dto.name.strip(),
            uen=dto.uen.strip() if dto.uen else None,
            base_currency=dto.base_currency.upper(),
            gst_registered=dto.gst_registered,
            financial_year_start_month=dto.financial_year_start_month,
            financial_year_start_day=dto.financial_year_start_day,
            status="active",
            created_by_user_id=owner_user_id,
            created_at=now,
            updated_at=now,
        )
        created = await self._repository.create(tenant)

        owner = TenantUser(
            id=str(uuid.uuid4()),
            tenant_id=created.id,
            user_id=owner_user_id,
            role="owner",
            status="active",
            created_at=now,
        )
        await self._repository.add_user(owner)

        if getattr(self._settings, "default_coa_seed", True):
            await self._repository.seed_default_coa(created.id)

        await self._repository.write_audit_tenant_created(
            tenant_id=created.id, user_id=owner_user_id
        )

        return self._to_summary(created, role="owner")

    async def get_tenant(self, tenant_id: TenantId, user_id: UserId) -> TenantSummaryResponse:
        tenant = await self._repository.get_for_active_member(tenant_id, user_id)
        if tenant is None:
            raise TenantNotFoundError(str(tenant_id))
        role = await self._repository.get_user_role(tenant_id, user_id)
        assert role is not None
        return self._to_summary(tenant, role=role)

    async def list_tenants(self, user_id: UserId) -> list[TenantListItemResponse]:
        rows = await self._repository.list_for_active_user(user_id)
        return [
            TenantListItemResponse(
                id=str(t.id),
                name=t.name,
                uen=t.uen,
                base_currency=t.base_currency,
                gst_registered=t.gst_registered,
                financial_year_start_month=t.financial_year_start_month,
                financial_year_start_day=t.financial_year_start_day,
                status=t.status,
                role=role,
                created_at=t.created_at,
            )
            for t, role in rows
        ]

    async def list_coa(
        self, tenant_id: TenantId, user_id: UserId
    ) -> list[CoaAccountResponse]:
        tenant = await self._repository.get_for_active_member(tenant_id, user_id)
        if tenant is None:
            raise TenantNotFoundError(str(tenant_id))
        rows = await self._repository.list_coa_for_tenant(tenant_id)
        return [
            CoaAccountResponse(
                id=r.id,
                code=r.code,
                name=r.name,
                type=r.account_type,
                parent_id=r.parent_id,
                is_active=r.is_active,
                is_system_default=r.is_system_default,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def add_user(
        self, tenant_id: TenantId, dto: AddUserRequest, actor_user_id: UserId
    ) -> TenantUserResponse:
        actor_role = await self._repository.get_user_role(tenant_id, actor_user_id)
        if actor_role is None:
            raise TenantNotFoundError(str(tenant_id))
        if actor_role != "owner":
            raise InsufficientPermissionError("Only the tenant owner can add users.")

        existing_role = await self._repository.get_user_role(
            tenant_id, UserId(uuid.UUID(dto.user_id))
        )
        if existing_role is not None:
            raise UserAlreadyMemberError(dto.user_id, str(tenant_id))

        now = datetime.now(UTC)
        tenant_user = TenantUser(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=UserId(uuid.UUID(dto.user_id)),
            role=dto.role,
            status="active",
            created_at=now,
        )
        created = await self._repository.add_user(tenant_user)
        return TenantUserResponse(
            id=str(created.id),
            tenant_id=str(created.tenant_id),
            user_id=str(created.user_id),
            role=created.role,
            created_at=created.created_at,
        )

    @staticmethod
    def _to_summary(tenant: Tenant, *, role: str) -> TenantSummaryResponse:
        return TenantSummaryResponse(
            id=str(tenant.id),
            name=tenant.name,
            uen=tenant.uen,
            base_currency=tenant.base_currency,
            gst_registered=tenant.gst_registered,
            financial_year_start_month=tenant.financial_year_start_month,
            financial_year_start_day=tenant.financial_year_start_day,
            status=tenant.status,
            role=role,
            created_at=tenant.created_at,
        )
