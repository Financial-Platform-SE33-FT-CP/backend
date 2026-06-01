"""US-8 RBAC: who may create/issue invoices vs. view only."""

from __future__ import annotations

from accounting_shared.rbac import (
    P_ACCOUNTING_CREATE,
    P_ACCOUNTING_DELETE,
    P_ACCOUNTING_POST,
    P_ACCOUNTING_READ,
    P_ACCOUNTING_UPDATE,
    TenantRole,
    role_has_permission,
)

_WRITE_PERMS = (
    P_ACCOUNTING_CREATE,
    P_ACCOUNTING_UPDATE,
    P_ACCOUNTING_POST,
    P_ACCOUNTING_DELETE,
)


def test_owner_can_create_and_issue() -> None:
    for perm in (*_WRITE_PERMS, P_ACCOUNTING_READ):
        assert role_has_permission(TenantRole.OWNER, perm)


def test_accountant_can_create_and_issue() -> None:
    for perm in (*_WRITE_PERMS, P_ACCOUNTING_READ):
        assert role_has_permission(TenantRole.ACCOUNTANT, perm)


def test_viewer_can_only_read() -> None:
    assert role_has_permission(TenantRole.VIEWER, P_ACCOUNTING_READ)
    for perm in _WRITE_PERMS:
        assert not role_has_permission(TenantRole.VIEWER, perm)
