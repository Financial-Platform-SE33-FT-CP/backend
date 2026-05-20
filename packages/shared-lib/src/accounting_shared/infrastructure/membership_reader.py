"""Load tenant membership role from the shared ``tenant_users`` table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.infrastructure.tenant_membership_model import TenantUserMembershipModel
from accounting_shared.types import TenantId, UserId


async def get_active_membership_role(
    session: AsyncSession,
    *,
    tenant_id: TenantId,
    user_id: UserId,
) -> str | None:
    """Return persisted role string for an active membership, or ``None``."""
    stmt = select(TenantUserMembershipModel.role).where(
        TenantUserMembershipModel.tenant_id == tenant_id,
        TenantUserMembershipModel.user_id == user_id,
        TenantUserMembershipModel.status == "active",
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
