from __future__ import annotations

import uuid
from datetime import UTC, datetime

from accounting_shared.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from accounting_shared.rbac import (
    P_COA_READ,
    P_TENANT_MEMBER_ADD,
    P_TENANT_MEMBER_LIST,
    P_TENANT_MEMBER_REMOVE,
    P_TENANT_MEMBER_ROLE_UPDATE,
    P_TENANT_READ,
    TenantRole,
    normalize_role,
    permissions_for_role,
)
from accounting_shared.types import TenantId, UserId, new_tenant_id

from ..domain.entities import Tenant, TenantUser
from ..domain.exceptions import UserAlreadyMemberError
from ..domain.repository import TenantRepository
from .authorization import evaluate_tenant_permission
from .dto import (
    CoaAccountResponse,
    CreateTenantRequest,
    InviteMemberRequest,
    MemberDetailsResponse,
    MeRoleResponse,
    TenantListItemResponse,
    TenantSummaryResponse,
    TenantUserResponse,
    UpdateMemberRoleRequest,
)

SUPPORTED_CURRENCIES = frozenset({"SGD", "USD", "EUR", "GBP", "AUD"})


class TenantService:
    """Application service for tenant management."""

    def __init__(self, repository: TenantRepository, settings: object) -> None:
        self._repository = repository
        self._settings = settings

    async def _require_membership_permission(
        self, tenant_id: TenantId, user_id: UserId, permission: str
    ) -> TenantRole:
        ev = await evaluate_tenant_permission(
            self._repository, tenant_id=tenant_id, user_id=user_id, permission=permission
        )
        if ev.allowed and ev.role is not None:
            return ev.role
        if ev.reason == "tenant_not_found":
            raise NotFoundError("Tenant not found.")
        if ev.reason == "not_member":
            raise ForbiddenError("Not a member of this tenant.")
        raise ForbiddenError("You do not have permission to perform this action.")

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
            role=TenantRole.OWNER.value,
            status="active",
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_user(owner)

        if getattr(self._settings, "default_coa_seed", True):
            await self._repository.seed_default_coa(created.id)

        await self._repository.write_audit_tenant_created(
            tenant_id=created.id, user_id=owner_user_id
        )

        return self._to_summary(created, role=TenantRole.OWNER.value)

    async def get_tenant(self, tenant_id: TenantId, user_id: UserId) -> TenantSummaryResponse:
        await self._require_membership_permission(tenant_id, user_id, P_TENANT_READ)
        tenant = await self._repository.get_by_id(tenant_id)
        assert tenant is not None
        raw = await self._repository.get_user_role(tenant_id, user_id)
        assert raw is not None
        role = normalize_role(raw)
        return self._to_summary(tenant, role=role.value)

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
                role=normalize_role(role).value,
                created_at=t.created_at,
            )
            for t, role in rows
        ]

    async def get_my_role(self, tenant_id: TenantId, user_id: UserId) -> MeRoleResponse:
        await self._require_membership_permission(tenant_id, user_id, P_TENANT_READ)
        raw = await self._repository.get_user_role(tenant_id, user_id)
        assert raw is not None
        role = normalize_role(raw)
        perms = sorted(permissions_for_role(role))
        return MeRoleResponse(
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            role=role.value,
            permissions=perms,
        )

    async def list_members(
        self, tenant_id: TenantId, actor_user_id: UserId
    ) -> list[MemberDetailsResponse]:
        await self._require_membership_permission(tenant_id, actor_user_id, P_TENANT_MEMBER_LIST)
        rows = await self._repository.list_tenant_members(tenant_id)
        return [
            MemberDetailsResponse(
                user_id=str(r.user_id),
                email=r.email,
                role=normalize_role(r.role).value,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def list_coa(self, tenant_id: TenantId, user_id: UserId) -> list[CoaAccountResponse]:
        await self._require_membership_permission(tenant_id, user_id, P_COA_READ)
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

    async def invite_member(
        self, tenant_id: TenantId, dto: InviteMemberRequest, actor_user_id: UserId
    ) -> TenantUserResponse:
        await self._require_membership_permission(tenant_id, actor_user_id, P_TENANT_MEMBER_ADD)

        try:
            target_role = normalize_role(dto.role)
        except ValueError as e:
            raise BadRequestError("Invalid tenant role.") from e

        if dto.user_id is not None:
            target_user_id = UserId(uuid.UUID(dto.user_id))
        elif dto.email is not None:
            resolved = await self._repository.find_user_id_by_email(dto.email)
            if resolved is None:
                raise NotFoundError("No user found for that email address.")
            target_user_id = resolved
        else:
            raise ValidationError("Provide user_id or email.")

        if await self._repository.get_user_role(tenant_id, target_user_id) is not None:
            raise UserAlreadyMemberError(str(target_user_id), str(tenant_id))

        now = datetime.now(UTC)
        tenant_user = TenantUser(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=target_user_id,
            role=target_role.value,
            status="active",
            created_at=now,
            updated_at=now,
        )
        created = await self._repository.add_user(tenant_user)
        return TenantUserResponse(
            id=str(created.id),
            tenant_id=str(created.tenant_id),
            user_id=str(created.user_id),
            role=normalize_role(created.role).value,
            created_at=created.created_at,
        )

    async def update_member_role(
        self,
        tenant_id: TenantId,
        target_user_id: UserId,
        dto: UpdateMemberRoleRequest,
        actor_user_id: UserId,
    ) -> MemberDetailsResponse:
        await self._require_membership_permission(
            tenant_id, actor_user_id, P_TENANT_MEMBER_ROLE_UPDATE
        )

        try:
            new_role = normalize_role(dto.role)
        except ValueError as e:
            raise BadRequestError("Invalid tenant role.") from e
        target_before = await self._repository.get_user_role(tenant_id, target_user_id)
        if target_before is None:
            raise NotFoundError("Member not found in this tenant.")

        current = normalize_role(target_before)
        owners = await self._repository.count_active_owners(tenant_id)

        if current == TenantRole.OWNER and new_role != TenantRole.OWNER and owners <= 1:
            raise ForbiddenError("Cannot change role of the last owner.")

        ok = await self._repository.update_membership_role(
            tenant_id, target_user_id, new_role.value
        )
        assert ok
        rows = await self._repository.list_tenant_members(tenant_id)
        for r in rows:
            if r.user_id == target_user_id:
                return MemberDetailsResponse(
                    user_id=str(r.user_id),
                    email=r.email,
                    role=new_role.value,
                    created_at=r.created_at,
                )
        raise NotFoundError("Member not found after update.")

    async def remove_member(
        self, tenant_id: TenantId, target_user_id: UserId, actor_user_id: UserId
    ) -> None:
        await self._require_membership_permission(tenant_id, actor_user_id, P_TENANT_MEMBER_REMOVE)

        current_raw = await self._repository.get_user_role(tenant_id, target_user_id)
        if current_raw is None:
            raise NotFoundError("Member not found in this tenant.")

        current = normalize_role(current_raw)
        owners = await self._repository.count_active_owners(tenant_id)

        if current == TenantRole.OWNER and owners <= 1:
            raise ForbiddenError("Cannot remove the last owner from the tenant.")

        await self._repository.remove_user(tenant_id, target_user_id)

    @staticmethod
    def _to_summary(tenant: Tenant, *, role: str) -> TenantSummaryResponse:
        canonical = normalize_role(role).value
        return TenantSummaryResponse(
            id=str(tenant.id),
            name=tenant.name,
            uen=tenant.uen,
            base_currency=tenant.base_currency,
            gst_registered=tenant.gst_registered,
            financial_year_start_month=tenant.financial_year_start_month,
            financial_year_start_day=tenant.financial_year_start_day,
            status=tenant.status,
            role=canonical,
            created_at=tenant.created_at,
        )
