"""Centralized tenant RBAC evaluation (US-3)."""

from __future__ import annotations

from dataclasses import dataclass

from accounting_shared.rbac import TenantRole, normalize_role, role_has_permission
from accounting_shared.types import TenantId, UserId

from ..domain.repository import TenantRepository


@dataclass(frozen=True, slots=True)
class TenantPermissionEvaluation:
    """Result of a membership + permission check (no side effects)."""

    allowed: bool
    role: TenantRole | None
    reason: str | None


async def evaluate_tenant_permission(
    repository: TenantRepository,
    *,
    tenant_id: TenantId,
    user_id: UserId,
    permission: str,
) -> TenantPermissionEvaluation:
    """Load membership from the DB and decide if *permission* is granted."""
    if not await repository.tenant_exists(tenant_id):
        return TenantPermissionEvaluation(False, None, "tenant_not_found")

    raw = await repository.get_user_role(tenant_id, user_id)
    if raw is None:
        return TenantPermissionEvaluation(False, None, "not_member")

    role = normalize_role(raw)
    if not role_has_permission(role, permission):
        return TenantPermissionEvaluation(False, role, "permission_denied")

    return TenantPermissionEvaluation(True, role, None)
