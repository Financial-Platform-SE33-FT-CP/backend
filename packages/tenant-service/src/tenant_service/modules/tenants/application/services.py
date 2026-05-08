from __future__ import annotations

from datetime import datetime

import httpx
from accounting_shared.types import TenantId, UserId, new_tenant_id

from ..domain.entities import Tenant, TenantUser
from ..domain.exceptions import (
    TenantNotFoundError,
    TenantSlugExistsError,
    UserAlreadyMemberError,
)
from ..domain.repository import TenantRepository
from .dto import AddUserRequest, CreateTenantRequest, TenantResponse, TenantUserResponse


class TenantService:
    """Application service for tenant management."""

    def __init__(self, repository: TenantRepository, settings: object) -> None:
        self._repository = repository
        self._settings = settings

    async def create_tenant(
        self, dto: CreateTenantRequest, owner_user_id: UserId
    ) -> TenantResponse:
        """Create a new tenant and seed the default chart of accounts."""
        existing = await self._repository.get_by_slug(dto.slug)
        if existing:
            raise TenantSlugExistsError(dto.slug)

        now = datetime.utcnow()
        tenant = Tenant(
            id=new_tenant_id(),
            name=dto.name,
            slug=dto.slug,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        created = await self._repository.create(tenant)

        # Add the owner as admin
        owner = TenantUser(
            id=str(new_tenant_id()),
            tenant_id=created.id,
            user_id=owner_user_id,
            role="admin",
            created_at=now,
        )
        await self._repository.add_user(owner)

        # Seed default chart of accounts if enabled
        if getattr(self._settings, "default_coa_seed", True):
            await self._seed_default_coa(created.id)

        return self._to_tenant_response(created)

    async def get_tenant(self, tenant_id: TenantId) -> TenantResponse:
        """Get a tenant by ID."""
        tenant = await self._repository.get_by_id(tenant_id)
        if not tenant:
            raise TenantNotFoundError(str(tenant_id))
        return self._to_tenant_response(tenant)

    async def list_tenants(self, user_id: UserId) -> list[TenantResponse]:
        """List tenants accessible to a user."""
        tenants = await self._repository.list_for_user(user_id)
        return [self._to_tenant_response(t) for t in tenants]

    async def verify_tenant(self, tenant_id: TenantId) -> bool:
        """Verify a tenant exists and is active."""
        tenant = await self._repository.get_by_id(tenant_id)
        return tenant is not None and tenant.is_active

    async def add_user(
        self, tenant_id: TenantId, dto: AddUserRequest, actor_user_id: UserId
    ) -> TenantUserResponse:
        """Add a user to a tenant (actor must be admin)."""
        actor_role = await self._repository.get_user_role(tenant_id, actor_user_id)
        if actor_role != "admin":
            from ..domain.exceptions import InsufficientPermissionError

            raise InsufficientPermissionError(
                "Only tenant admins can add users"
            )

        # Check if user is already a member
        existing_role = await self._repository.get_user_role(tenant_id, UserId(dto.user_id))
        if existing_role is not None:
            raise UserAlreadyMemberError(dto.user_id, str(tenant_id))

        now = datetime.utcnow()
        tenant_user = TenantUser(
            id=str(new_tenant_id()),
            tenant_id=tenant_id,
            user_id=UserId(dto.user_id),
            role=dto.role,
            created_at=now,
        )
        created = await self._repository.add_user(tenant_user)
        return TenantUserResponse(
            id=created.id,
            tenant_id=str(created.tenant_id),
            user_id=str(created.user_id),
            role=created.role,
            created_at=created.created_at,
        )

    async def remove_user(
        self, tenant_id: TenantId, user_id: UserId, actor_user_id: UserId
    ) -> None:
        """Remove a user from a tenant (actor must be admin)."""
        actor_role = await self._repository.get_user_role(tenant_id, actor_user_id)
        if actor_role != "admin":
            from ..domain.exceptions import InsufficientPermissionError

            raise InsufficientPermissionError(
                "Only tenant admins can remove users"
            )

        await self._repository.remove_user(tenant_id, user_id)

    async def _seed_default_coa(self, tenant_id: TenantId) -> None:
        """Call the COA service to seed the default chart of accounts."""
        coa_url = (
            f"http://coa-service:8000/api/v1/coa/seed/{tenant_id}"
        )
        async with httpx.AsyncClient() as client:
            try:
                await client.post(coa_url, json={}, timeout=30.0)
            except httpx.HTTPError:
                # Log and continue — seeding failure should not block creation
                import structlog

                logger = structlog.get_logger(__name__)
                logger.warning(
                    "coa_seed_failed",
                    tenant_id=str(tenant_id),
                )

    @staticmethod
    def _to_tenant_response(tenant: Tenant) -> TenantResponse:
        return TenantResponse(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )
