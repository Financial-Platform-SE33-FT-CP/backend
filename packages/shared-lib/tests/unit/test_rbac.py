"""Unit tests for accounting_shared.rbac module."""

from __future__ import annotations

import pytest

from accounting_shared.rbac import (
    ALL_PERMISSIONS,
    P_ACCOUNTING_CREATE,
    P_ACCOUNTING_DELETE,
    P_ACCOUNTING_POST,
    P_ACCOUNTING_READ,
    P_ACCOUNTING_UPDATE,
    P_COA_CREATE,
    P_COA_DELETE,
    P_COA_READ,
    P_COA_UPDATE,
    P_TENANT_MEMBER_ADD,
    P_TENANT_MEMBER_LIST,
    P_TENANT_MEMBER_REMOVE,
    P_TENANT_MEMBER_ROLE_UPDATE,
    P_TENANT_READ,
    P_TENANT_UPDATE,
    ROLE_PERMISSIONS,
    TenantRole,
    expand_legacy_role_string,
    normalize_role,
    permissions_for_role,
    permissions_for_role_string,
    role_has_permission,
    tenant_role_to_frontend_api,
)


class TestTenantRole:
    """Tests for TenantRole enum."""

    def test_owner_role_value(self):
        """OWNER role should have value 'OWNER'."""
        assert TenantRole.OWNER == "OWNER"

    def test_accountant_role_value(self):
        """ACCOUNTANT role should have value 'ACCOUNTANT'."""
        assert TenantRole.ACCOUNTANT == "ACCOUNTANT"

    def test_viewer_role_value(self):
        """VIEWER role should have value 'VIEWER'."""
        assert TenantRole.VIEWER == "VIEWER"

    def test_tenant_role_is_str_enum(self):
        """TenantRole should be a string enum."""
        assert isinstance(TenantRole.OWNER, str)
        assert isinstance(TenantRole.ACCOUNTANT, str)
        assert isinstance(TenantRole.VIEWER, str)

    def test_tenant_role_enum_members(self):
        """TenantRole should have exactly 3 members."""
        assert len(TenantRole) == 3
        assert set(TenantRole) == {TenantRole.OWNER, TenantRole.ACCOUNTANT, TenantRole.VIEWER}


class TestPermissionConstants:
    """Tests for permission string constants."""

    def test_tenant_permissions(self):
        """Tenant permission constants should have correct values."""
        assert P_TENANT_READ == "tenant:read"
        assert P_TENANT_UPDATE == "tenant:update"
        assert P_TENANT_MEMBER_LIST == "tenant:member:list"
        assert P_TENANT_MEMBER_ADD == "tenant:member:add"
        assert P_TENANT_MEMBER_REMOVE == "tenant:member:remove"
        assert P_TENANT_MEMBER_ROLE_UPDATE == "tenant:member:role:update"

    def test_accounting_permissions(self):
        """Accounting permission constants should have correct values."""
        assert P_ACCOUNTING_READ == "accounting:read"
        assert P_ACCOUNTING_CREATE == "accounting:create"
        assert P_ACCOUNTING_UPDATE == "accounting:update"
        assert P_ACCOUNTING_POST == "accounting:post"
        assert P_ACCOUNTING_DELETE == "accounting:delete"

    def test_coa_permissions(self):
        """COA permission constants should have correct values."""
        assert P_COA_READ == "coa:read"
        assert P_COA_CREATE == "coa:create"
        assert P_COA_UPDATE == "coa:update"
        assert P_COA_DELETE == "coa:delete"

    def test_legacy_aliases(self):
        """Legacy aliases should match their new counterparts."""
        from accounting_shared.rbac import (
            P_TENANT_MEMBERS_LIST,
            P_TENANT_USER_INVITE,
            P_TENANT_USER_REMOVE,
            P_TENANT_USER_ROLE_UPDATE,
        )

        assert P_TENANT_MEMBERS_LIST == P_TENANT_MEMBER_LIST
        assert P_TENANT_USER_INVITE == P_TENANT_MEMBER_ADD
        assert P_TENANT_USER_REMOVE == P_TENANT_MEMBER_REMOVE
        assert P_TENANT_USER_ROLE_UPDATE == P_TENANT_MEMBER_ROLE_UPDATE


class TestRolePermissions:
    """Tests for ROLE_PERMISSIONS mapping."""

    def test_owner_has_all_permissions(self):
        """OWNER role should have all permissions."""
        owner_permissions = ROLE_PERMISSIONS[TenantRole.OWNER]
        assert owner_permissions == ALL_PERMISSIONS

    def test_accountant_permissions(self):
        """ACCOUNTANT role should have accounting + COA + tenant:read permissions."""
        accountant_permissions = ROLE_PERMISSIONS[TenantRole.ACCOUNTANT]
        expected = {
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
        assert accountant_permissions == expected

    def test_viewer_permissions(self):
        """VIEWER role should have read-only permissions."""
        viewer_permissions = ROLE_PERMISSIONS[TenantRole.VIEWER]
        expected = {
            P_TENANT_READ,
            P_ACCOUNTING_READ,
            P_COA_READ,
        }
        assert viewer_permissions == expected

    def test_all_permissions_is_complete(self):
        """ALL_PERMISSIONS should contain all defined permission constants."""
        expected_permissions = {
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
        assert expected_permissions == ALL_PERMISSIONS

    def test_role_permissions_covers_all_roles(self):
        """ROLE_PERMISSIONS should have entries for all TenantRole members."""
        for role in TenantRole:
            assert role in ROLE_PERMISSIONS


class TestPermissionsForRole:
    """Tests for permissions_for_role function."""

    def test_owner_permissions(self):
        """permissions_for_role(OWNER) should return all permissions."""
        permissions = permissions_for_role(TenantRole.OWNER)
        assert permissions == ALL_PERMISSIONS

    def test_accountant_permissions(self):
        """permissions_for_role(ACCOUNTANT) should return accountant permissions."""
        permissions = permissions_for_role(TenantRole.ACCOUNTANT)
        expected = ROLE_PERMISSIONS[TenantRole.ACCOUNTANT]
        assert permissions == expected

    def test_viewer_permissions(self):
        """permissions_for_role(VIEWER) should return viewer permissions."""
        permissions = permissions_for_role(TenantRole.VIEWER)
        expected = ROLE_PERMISSIONS[TenantRole.VIEWER]
        assert permissions == expected

    def test_returns_frozenset(self):
        """permissions_for_role should return frozenset."""
        for role in TenantRole:
            permissions = permissions_for_role(role)
            assert isinstance(permissions, frozenset)


class TestNormalizeRole:
    """Tests for normalize_role function."""

    @pytest.mark.parametrize(
        "input_role,expected",
        [
            ("owner", TenantRole.OWNER),
            ("admin", TenantRole.OWNER),
            ("accountant", TenantRole.ACCOUNTANT),
            ("manager", TenantRole.ACCOUNTANT),
            ("viewer", TenantRole.VIEWER),
            ("OWNER", TenantRole.OWNER),
            ("ADMIN", TenantRole.OWNER),
            ("ACCOUNTANT", TenantRole.ACCOUNTANT),
            ("MANAGER", TenantRole.ACCOUNTANT),
            ("VIEWER", TenantRole.VIEWER),
            ("Owner", TenantRole.OWNER),
            ("Admin", TenantRole.OWNER),
            ("Accountant", TenantRole.ACCOUNTANT),
            ("Manager", TenantRole.ACCOUNTANT),
            ("Viewer", TenantRole.VIEWER),
        ],
    )
    def test_normalize_role_valid_inputs(self, input_role, expected):
        """normalize_role should normalize valid role strings."""
        assert normalize_role(input_role) == expected

    def test_normalize_role_strips_whitespace(self):
        """normalize_role should strip whitespace."""
        assert normalize_role("  owner  ") == TenantRole.OWNER
        assert normalize_role("\taccountant\n") == TenantRole.ACCOUNTANT

    def test_normalize_role_empty_string_raises_error(self):
        """normalize_role should raise ValueError for empty string."""
        with pytest.raises(ValueError, match="Invalid tenant role: ''"):
            normalize_role("")

    def test_normalize_role_none_raises_error(self):
        """normalize_role should raise ValueError for None."""
        with pytest.raises(ValueError, match="Invalid tenant role: ''"):
            normalize_role(None)

    def test_normalize_role_invalid_string_raises_error(self):
        """normalize_role should raise ValueError for invalid role string."""
        with pytest.raises(ValueError, match="Invalid tenant role: 'invalid'"):
            normalize_role("invalid")

    def test_normalize_role_invalid_case_raises_error(self):
        """normalize_role should raise ValueError for invalid case variations."""
        with pytest.raises(ValueError, match="Invalid tenant role: 'INVALID'"):
            normalize_role("INVALID")


class TestTenantRoleToFrontendApi:
    """Tests for tenant_role_to_frontend_api function."""

    @pytest.mark.parametrize(
        "role,expected",
        [
            (TenantRole.OWNER, "admin"),
            (TenantRole.ACCOUNTANT, "manager"),
            (TenantRole.VIEWER, "viewer"),
        ],
    )
    def test_tenant_role_to_frontend_api(self, role, expected):
        """tenant_role_to_frontend_api should return correct lowercase string."""
        assert tenant_role_to_frontend_api(role) == expected

    def test_returns_string(self):
        """tenant_role_to_frontend_api should return string."""
        for role in TenantRole:
            result = tenant_role_to_frontend_api(role)
            assert isinstance(result, str)


class TestRoleHasPermission:
    """Tests for role_has_permission function."""

    def test_owner_has_all_permissions(self):
        """OWNER should have all permissions."""
        for permission in ALL_PERMISSIONS:
            assert role_has_permission(TenantRole.OWNER, permission) is True

    def test_accountant_has_accounting_permissions(self):
        """ACCOUNTANT should have accounting permissions."""
        accounting_permissions = [
            P_ACCOUNTING_READ,
            P_ACCOUNTING_CREATE,
            P_ACCOUNTING_UPDATE,
            P_ACCOUNTING_POST,
            P_ACCOUNTING_DELETE,
        ]
        for permission in accounting_permissions:
            assert role_has_permission(TenantRole.ACCOUNTANT, permission) is True

    def test_accountant_has_coa_permissions(self):
        """ACCOUNTANT should have COA permissions."""
        coa_permissions = [P_COA_READ, P_COA_CREATE, P_COA_UPDATE, P_COA_DELETE]
        for permission in coa_permissions:
            assert role_has_permission(TenantRole.ACCOUNTANT, permission) is True

    def test_accountant_has_tenant_read(self):
        """ACCOUNTANT should have tenant:read permission."""
        assert role_has_permission(TenantRole.ACCOUNTANT, P_TENANT_READ) is True

    def test_accountant_missing_tenant_update(self):
        """ACCOUNTANT should not have tenant:update permission."""
        assert role_has_permission(TenantRole.ACCOUNTANT, P_TENANT_UPDATE) is False

    def test_viewer_has_read_permissions(self):
        """VIEWER should have read-only permissions."""
        read_permissions = [P_TENANT_READ, P_ACCOUNTING_READ, P_COA_READ]
        for permission in read_permissions:
            assert role_has_permission(TenantRole.VIEWER, permission) is True

    def test_viewer_missing_write_permissions(self):
        """VIEWER should not have write permissions."""
        write_permissions = [
            P_TENANT_UPDATE,
            P_TENANT_MEMBER_ADD,
            P_TENANT_MEMBER_REMOVE,
            P_TENANT_MEMBER_ROLE_UPDATE,
            P_ACCOUNTING_CREATE,
            P_ACCOUNTING_UPDATE,
            P_ACCOUNTING_POST,
            P_ACCOUNTING_DELETE,
            P_COA_CREATE,
            P_COA_UPDATE,
            P_COA_DELETE,
        ]
        for permission in write_permissions:
            assert role_has_permission(TenantRole.VIEWER, permission) is False


class TestPermissionsForRoleString:
    """Tests for permissions_for_role_string function."""

    def test_with_owner_string(self):
        """permissions_for_role_string should work with owner string."""
        permissions = permissions_for_role_string("owner")
        assert permissions == permissions_for_role(TenantRole.OWNER)

    def test_with_accountant_string(self):
        """permissions_for_role_string should work with accountant string."""
        permissions = permissions_for_role_string("accountant")
        assert permissions == permissions_for_role(TenantRole.ACCOUNTANT)

    def test_with_viewer_string(self):
        """permissions_for_role_string should work with viewer string."""
        permissions = permissions_for_role_string("viewer")
        assert permissions == permissions_for_role(TenantRole.VIEWER)

    def test_with_admin_string(self):
        """permissions_for_role_string should work with admin string (alias for owner)."""
        permissions = permissions_for_role_string("admin")
        assert permissions == permissions_for_role(TenantRole.OWNER)

    def test_with_manager_string(self):
        """permissions_for_role_string should work with manager string (alias for accountant)."""
        permissions = permissions_for_role_string("manager")
        assert permissions == permissions_for_role(TenantRole.ACCOUNTANT)

    def test_with_uppercase_string(self):
        """permissions_for_role_string should work with uppercase string."""
        permissions = permissions_for_role_string("OWNER")
        assert permissions == permissions_for_role(TenantRole.OWNER)

    def test_with_invalid_string_raises_error(self):
        """permissions_for_role_string should raise ValueError for invalid string."""
        with pytest.raises(ValueError, match="Invalid tenant role: 'invalid'"):
            permissions_for_role_string("invalid")


class TestExpandLegacyRoleString:
    """Tests for expand_legacy_role_string function."""

    @pytest.mark.parametrize(
        "input_role,expected",
        [
            ("owner", "OWNER"),
            ("admin", "OWNER"),
            ("accountant", "ACCOUNTANT"),
            ("manager", "ACCOUNTANT"),
            ("viewer", "VIEWER"),
            ("OWNER", "OWNER"),
            ("ADMIN", "OWNER"),
            ("ACCOUNTANT", "ACCOUNTANT"),
            ("MANAGER", "ACCOUNTANT"),
            ("VIEWER", "VIEWER"),
        ],
    )
    def test_expand_legacy_role_string(self, input_role, expected):
        """expand_legacy_role_string should return canonical UPPER role string."""
        assert expand_legacy_role_string(input_role) == expected

    def test_returns_uppercase(self):
        """expand_legacy_role_string should always return uppercase."""
        for role_str in ["owner", "admin", "accountant", "manager", "viewer"]:
            result = expand_legacy_role_string(role_str)
            assert result == result.upper()

    def test_with_invalid_string_raises_error(self):
        """expand_legacy_role_string should raise ValueError for invalid string."""
        with pytest.raises(ValueError, match="Invalid tenant role: 'invalid'"):
            expand_legacy_role_string("invalid")
