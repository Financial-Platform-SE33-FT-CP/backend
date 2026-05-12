"""Tenant RBAC: roles, permissions, and role→permission mapping (US-3)."""

from __future__ import annotations

from enum import StrEnum

# --- Permission strings (API contract) ---

# Tenant administration
P_TENANT_READ = "tenant:read"
P_TENANT_UPDATE = "tenant:update"
P_TENANT_MEMBER_LIST = "tenant:member:list"
P_TENANT_MEMBER_ADD = "tenant:member:add"
P_TENANT_MEMBER_REMOVE = "tenant:member:remove"
P_TENANT_MEMBER_ROLE_UPDATE = "tenant:member:role:update"

# Legacy aliases (same values; older call sites / migrations)
P_TENANT_MEMBERS_LIST = P_TENANT_MEMBER_LIST
P_TENANT_USER_INVITE = P_TENANT_MEMBER_ADD
P_TENANT_USER_REMOVE = P_TENANT_MEMBER_REMOVE
P_TENANT_USER_ROLE_UPDATE = P_TENANT_MEMBER_ROLE_UPDATE

# Accounting (journal / operational accounting, not COA strings)
P_ACCOUNTING_READ = "accounting:read"
P_ACCOUNTING_CREATE = "accounting:create"
P_ACCOUNTING_UPDATE = "accounting:update"
P_ACCOUNTING_POST = "accounting:post"
P_ACCOUNTING_DELETE = "accounting:delete"

# Chart of accounts
P_COA_READ = "coa:read"
P_COA_CREATE = "coa:create"
P_COA_UPDATE = "coa:update"
P_COA_DELETE = "coa:delete"


class TenantRole(StrEnum):
    """Role stored per tenant membership (never trust client-supplied role strings)."""

    OWNER = "OWNER"
    ACCOUNTANT = "ACCOUNTANT"
    VIEWER = "VIEWER"


ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        P_TENANT_READ,
        P_TENANT_UPDATE,
        P_TENANT_MEMBER_LIST,
        P_TENANT_MEMBER_ADD,
        P_TENANT_MEMBER_REMOVE,
        P_TENANT_MEMBER_ROLE_UPDATE,
        P_ACCOUNTING_READ,
        P_ACCOUNTING_CREATE,
        P_ACCOUNTING_UPDATE,
        P_ACCOUNTING_POST,
        P_ACCOUNTING_DELETE,
        P_COA_READ,
        P_COA_CREATE,
        P_COA_UPDATE,
        P_COA_DELETE,
    }
)

ROLE_PERMISSIONS: dict[TenantRole, frozenset[str]] = {
    TenantRole.OWNER: ALL_PERMISSIONS,
    TenantRole.ACCOUNTANT: frozenset(
        {
            P_TENANT_READ,
            P_ACCOUNTING_READ,
            P_ACCOUNTING_CREATE,
            P_ACCOUNTING_UPDATE,
            P_ACCOUNTING_POST,
            P_ACCOUNTING_DELETE,
            P_COA_READ,
            P_COA_CREATE,
            P_COA_UPDATE,
            P_COA_DELETE,
        }
    ),
    TenantRole.VIEWER: frozenset(
        {
            P_TENANT_READ,
            P_ACCOUNTING_READ,
            P_COA_READ,
        }
    ),
}


def normalize_role(value: str) -> TenantRole:
    """Parse and normalize role names; accepts legacy lowercase from older rows."""
    v = (value or "").strip().upper()
    try:
        return TenantRole(v)
    except ValueError as e:
        msg = f"Invalid tenant role: {value!r}"
        raise ValueError(msg) from e


def permissions_for_role(role: TenantRole) -> frozenset[str]:
    """Return effective permissions for *role*."""
    return ROLE_PERMISSIONS[role]


def role_has_permission(role: TenantRole, permission: str) -> bool:
    """Return True if *role* grants *permission*."""
    return permission in ROLE_PERMISSIONS[role]


def permissions_for_role_string(role_str: str) -> frozenset[str]:
    """Resolve permissions from a persisted membership role string."""
    return permissions_for_role(normalize_role(role_str))


def expand_legacy_role_string(role_str: str) -> str:
    """Return canonical UPPER role string; maps legacy 'owner' -> OWNER."""
    return normalize_role(role_str).value
