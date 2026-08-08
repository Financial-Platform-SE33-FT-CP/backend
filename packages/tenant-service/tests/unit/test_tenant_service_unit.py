"""Unit tests for TenantService application service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from accounting_shared.audit_client import CreateAuditLogDTO
from accounting_shared.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from accounting_shared.types import TenantId, UserId

from tenant_service.modules.tenants.application.authorization import (
    TenantPermissionEvaluation,
)
from tenant_service.modules.tenants.application.dto import (
    CreateTenantRequest,
    InviteMemberRequest,
    UpdateMemberRoleRequest,
)
from tenant_service.modules.tenants.application.services import TenantService
from tenant_service.modules.tenants.domain.entities import (
    Tenant,
    TenantMemberRow,
    TenantUser,
)
from tenant_service.modules.tenants.domain.exceptions import UserAlreadyMemberError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_EVAL_PATH = "tenant_service.modules.tenants.application.services.evaluate_tenant_permission"


def _uid() -> UserId:
    return UserId(uuid.uuid4())


def _tid() -> TenantId:
    return TenantId(uuid.uuid4())


def _make_tenant(tid: TenantId, uid: UserId, name: str = "Acme") -> Tenant:
    now = datetime.now(UTC)
    return Tenant(
        id=tid,
        name=name,
        uen="202400001A",
        base_currency="SGD",
        gst_registered=False,
        financial_year_start_month=1,
        financial_year_start_day=1,
        status="active",
        created_by_user_id=uid,
        created_at=now,
        updated_at=now,
    )


def _allowed(uid: UserId, tid: TenantId, role: str = "OWNER") -> TenantPermissionEvaluation:
    return TenantPermissionEvaluation(True, role, None)


def _denied(reason: str = "not_member") -> TenantPermissionEvaluation:
    return TenantPermissionEvaluation(False, None, reason)


class _FakeAuditClient:
    """Records audit DTOs synchronously; mirrors AuditHttpClient.log_in_background."""

    def __init__(self) -> None:
        self.entries: list[CreateAuditLogDTO] = []

    def log_in_background(self, dto: CreateAuditLogDTO) -> None:
        self.entries.append(dto)


def _create_tenant_service(
    repo: MagicMock, audit_client: _FakeAuditClient | None = None
) -> TenantService:
    settings = MagicMock()
    settings.default_coa_seed = True
    return TenantService(repo, settings, audit_client=audit_client)


# ---------------------------------------------------------------------------
# create_tenant
# ---------------------------------------------------------------------------


class TestCreateTenant:
    """Tests for TenantService.create_tenant()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_create_tenant_success(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """Happy path: tenant created, owner membership added, COA seeded, audit written."""
        fixed_id = sample_tenant_id
        fixed_owner_id = sample_user_id
        now = datetime.now(UTC)

        repo = MagicMock()
        repo.create = AsyncMock(
            return_value=Tenant(
                id=fixed_id,
                name="Acme",
                uen="202400001A",
                base_currency="SGD",
                gst_registered=False,
                financial_year_start_month=1,
                financial_year_start_day=1,
                status="active",
                created_by_user_id=fixed_owner_id,
                created_at=now,
                updated_at=now,
            )
        )
        repo.add_user = AsyncMock(
            return_value=TenantUser(
                id=str(uuid.uuid4()),
                tenant_id=fixed_id,
                user_id=fixed_owner_id,
                role="OWNER",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        repo.seed_default_coa = AsyncMock()
        audit = _FakeAuditClient()
        service = _create_tenant_service(repo, audit)

        with patch(
            "tenant_service.modules.tenants.application.services.new_tenant_id",
            return_value=fixed_id,
        ):
            dto = CreateTenantRequest(
                name="Acme",
                uen="202400001A",
                base_currency="SGD",
                financial_year_start_month=1,
                financial_year_start_day=1,
            )
            result = await service.create_tenant(dto, fixed_owner_id)

        assert result.name == "Acme"
        assert result.base_currency == "SGD"
        assert result.role == "OWNER"
        assert result.id == str(fixed_id)
        repo.create.assert_awaited_once()
        repo.add_user.assert_awaited_once()
        repo.seed_default_coa.assert_awaited_once_with(fixed_id)
        assert len(audit.entries) == 1
        entry = audit.entries[0]
        assert entry.action == "TENANT_CREATED"
        assert entry.entity_type == "tenant"
        assert entry.entity_id == str(fixed_id)
        assert entry.user_id == fixed_owner_id

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_create_tenant_unsupported_currency(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """Unsupported currency raises ValidationError."""
        repo = MagicMock()
        service = _create_tenant_service(repo)
        dto = CreateTenantRequest(
            name="Bad",
            base_currency="ZZZ",
            financial_year_start_month=1,
            financial_year_start_day=1,
        )
        with pytest.raises(ValidationError):
            await service.create_tenant(dto, sample_user_id)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_create_tenant_no_coa_seed(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """COA seed skipped when settings.default_coa_seed is False."""
        fixed_id = sample_tenant_id
        uid = sample_user_id
        now = datetime.now(UTC)

        repo = MagicMock()
        repo.create = AsyncMock(
            return_value=Tenant(
                id=fixed_id,
                name="X",
                uen=None,
                base_currency="SGD",
                gst_registered=False,
                financial_year_start_month=1,
                financial_year_start_day=1,
                status="active",
                created_by_user_id=uid,
                created_at=now,
                updated_at=now,
            )
        )
        repo.add_user = AsyncMock(
            return_value=TenantUser(
                id=str(uuid.uuid4()),
                tenant_id=fixed_id,
                user_id=uid,
                role="OWNER",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        repo.seed_default_coa = AsyncMock()
        settings = MagicMock()
        settings.default_coa_seed = False
        service = TenantService(repo, settings)

        with patch(
            "tenant_service.modules.tenants.application.services.new_tenant_id",
            return_value=fixed_id,
        ):
            dto = CreateTenantRequest(
                name="X",
                base_currency="SGD",
                financial_year_start_month=1,
                financial_year_start_day=1,
            )
            await service.create_tenant(dto, uid)

        repo.seed_default_coa.assert_not_awaited()

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_create_tenant_strips_whitespace(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """Name is stripped of leading/trailing whitespace."""
        fixed_id = sample_tenant_id
        uid = sample_user_id
        now = datetime.now(UTC)

        repo = MagicMock()
        repo.create = AsyncMock(
            return_value=Tenant(
                id=fixed_id,
                name="Acme",
                uen=None,
                base_currency="SGD",
                gst_registered=False,
                financial_year_start_month=1,
                financial_year_start_day=1,
                status="active",
                created_by_user_id=uid,
                created_at=now,
                updated_at=now,
            )
        )
        repo.add_user = AsyncMock(
            return_value=TenantUser(
                id=str(uuid.uuid4()),
                tenant_id=fixed_id,
                user_id=uid,
                role="OWNER",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        repo.seed_default_coa = AsyncMock()
        settings = MagicMock()
        settings.default_coa_seed = False
        service = TenantService(repo, settings)

        with patch(
            "tenant_service.modules.tenants.application.services.new_tenant_id",
            return_value=fixed_id,
        ):
            dto = CreateTenantRequest(
                name="  Acme  ",
                base_currency="SGD",
                financial_year_start_month=1,
                financial_year_start_day=1,
            )
            result = await service.create_tenant(dto, uid)

        assert result.name == "Acme"
        create_arg = repo.create.call_args[0][0]
        assert create_arg.name == "Acme"

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_create_tenant_uppercase_currency(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """Lowercase currency is uppercased."""
        fixed_id = sample_tenant_id
        uid = sample_user_id
        now = datetime.now(UTC)

        repo = MagicMock()
        repo.create = AsyncMock(
            return_value=Tenant(
                id=fixed_id,
                name="X",
                uen=None,
                base_currency="SGD",
                gst_registered=False,
                financial_year_start_month=1,
                financial_year_start_day=1,
                status="active",
                created_by_user_id=uid,
                created_at=now,
                updated_at=now,
            )
        )
        repo.add_user = AsyncMock(
            return_value=TenantUser(
                id=str(uuid.uuid4()),
                tenant_id=fixed_id,
                user_id=uid,
                role="OWNER",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        repo.seed_default_coa = AsyncMock()
        settings = MagicMock()
        settings.default_coa_seed = False
        service = TenantService(repo, settings)

        with patch(
            "tenant_service.modules.tenants.application.services.new_tenant_id",
            return_value=fixed_id,
        ):
            dto = CreateTenantRequest(
                name="X",
                base_currency="sgd",
                financial_year_start_month=1,
                financial_year_start_day=1,
            )
            result = await service.create_tenant(dto, uid)

        assert result.base_currency == "SGD"


# ---------------------------------------------------------------------------
# get_tenant / list_tenants / get_my_role
# ---------------------------------------------------------------------------


class TestGetTenant:
    """Tests for TenantService.get_tenant()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_get_tenant_success(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id

        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=_make_tenant(tid, uid, "Acme"))
        repo.get_user_role = AsyncMock(return_value="OWNER")
        service = _create_tenant_service(repo)

        result = await service.get_tenant(tid, uid)

        assert result.name == "Acme"
        assert result.role == "OWNER"
        mock_eval.assert_awaited_once()

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_get_tenant_not_member_raises_forbidden(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _denied("not_member")
        repo = MagicMock()
        service = _create_tenant_service(repo)

        with pytest.raises(ForbiddenError):
            await service.get_tenant(sample_tenant_id, sample_user_id)


class TestListTenants:
    """Tests for TenantService.list_tenants()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_list_tenants_maps_roles(
        self, mock_eval: AsyncMock, sample_user_id: UserId
    ) -> None:
        uid = sample_user_id
        tid1 = _tid()
        tid2 = _tid()

        repo = MagicMock()
        repo.list_for_active_user = AsyncMock(
            return_value=[
                (_make_tenant(tid1, uid, "A"), "owner"),
                (_make_tenant(tid2, uid, "B"), "accountant"),
            ]
        )
        service = _create_tenant_service(repo)

        results = await service.list_tenants(uid)

        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"A", "B"}
        roles = {r.name: r.role for r in results}
        assert roles["A"] == "OWNER"
        assert roles["B"] == "ACCOUNTANT"


class TestGetMyRole:
    """Tests for TenantService.get_my_role()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_get_my_role_returns_permissions(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value="OWNER")
        service = _create_tenant_service(repo)

        result = await service.get_my_role(tid, uid)

        assert result.tenant_id == str(tid)
        assert result.user_id == str(uid)
        assert result.role == "OWNER"
        assert "tenant:read" in result.permissions
        assert "tenant:member:add" in result.permissions
        assert "coa:read" in result.permissions


# ---------------------------------------------------------------------------
# invite_member
# ---------------------------------------------------------------------------


class TestInviteMember:
    """Tests for TenantService.invite_member()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_invite_already_member_raises_conflict(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        invitee = _uid()

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value="OWNER")
        service = _create_tenant_service(repo)

        dto = InviteMemberRequest(user_id=str(invitee), role="VIEWER")
        with pytest.raises(UserAlreadyMemberError):
            await service.invite_member(tid, dto, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_invite_invalid_role_raises_bad_request(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        invitee = _uid()

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value=None)
        service = _create_tenant_service(repo)

        dto = InviteMemberRequest(user_id=str(invitee), role="SUPERUSER")
        with pytest.raises(BadRequestError):
            await service.invite_member(tid, dto, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_invite_email_not_found_raises_not_found(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id

        repo = MagicMock()
        repo.find_user_id_by_email = AsyncMock(return_value=None)
        service = _create_tenant_service(repo)

        dto = InviteMemberRequest(email="nobody@example.com", role="VIEWER")
        with pytest.raises(NotFoundError):
            await service.invite_member(tid, dto, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_invite_email_resolved_success(
        self,
        mock_eval: AsyncMock,
        sample_tenant_id: TenantId,
        sample_user_id: UserId,
    ) -> None:
        """Invite by email resolves user_id and creates membership."""
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        invitee = _uid()
        now = datetime.now(UTC)

        repo = MagicMock()
        repo.find_user_id_by_email = AsyncMock(return_value=invitee)
        repo.get_user_role = AsyncMock(return_value=None)
        repo.add_user = AsyncMock(
            return_value=TenantUser(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                user_id=invitee,
                role="VIEWER",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        audit = _FakeAuditClient()
        service = _create_tenant_service(repo, audit)

        dto = InviteMemberRequest(email="new@example.com", role="VIEWER")
        result = await service.invite_member(tid, dto, uid)

        assert str(result.user_id) == str(invitee)
        assert result.role == "VIEWER"
        repo.find_user_id_by_email.assert_awaited_once_with("new@example.com")
        repo.add_user.assert_awaited_once()
        assert len(audit.entries) == 1
        entry = audit.entries[0]
        assert entry.action == "MEMBER_ADDED"
        assert entry.entity_type == "tenant"
        assert entry.user_id == uid
        assert entry.changes == {"user_id": str(invitee), "role": "VIEWER"}

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_invite_no_user_id_or_email_raises_validation(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """InviteMemberRequest with neither user_id nor email raises ValueError at DTO level."""
        with pytest.raises(ValueError, match="Provide exactly one"):
            InviteMemberRequest(role="VIEWER")

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_invite_duplicate_user_id_and_email_raises_validation(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """InviteMemberRequest with both user_id and email raises ValueError."""
        with pytest.raises(ValueError, match="Provide exactly one"):
            InviteMemberRequest(user_id=str(_uid()), email="a@b.com", role="VIEWER")


# ---------------------------------------------------------------------------
# remove_member
# ---------------------------------------------------------------------------


class TestRemoveMember:
    """Tests for TenantService.remove_member()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_remove_member_not_found(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        target = _uid()

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value=None)
        service = _create_tenant_service(repo)

        with pytest.raises(NotFoundError):
            await service.remove_member(tid, target, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_remove_last_owner_forbidden(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        target = _uid()

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value="OWNER")
        repo.count_active_owners = AsyncMock(return_value=1)
        service = _create_tenant_service(repo)

        with pytest.raises(ForbiddenError):
            await service.remove_member(tid, target, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_remove_member_success(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        target = _uid()

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value="VIEWER")
        repo.count_active_owners = AsyncMock(return_value=2)
        repo.remove_user = AsyncMock()
        audit = _FakeAuditClient()
        service = _create_tenant_service(repo, audit)

        await service.remove_member(tid, target, uid)
        repo.remove_user.assert_awaited_once_with(tid, target)
        assert len(audit.entries) == 1
        entry = audit.entries[0]
        assert entry.action == "MEMBER_REMOVED"
        assert entry.entity_type == "tenant"
        assert entry.user_id == uid
        assert entry.changes == {"user_id": str(target)}


# ---------------------------------------------------------------------------
# update_member_role
# ---------------------------------------------------------------------------


class TestUpdateMemberRole:
    """Tests for TenantService.update_member_role()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_update_role_last_owner_demote_forbidden(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        target = _uid()

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value="OWNER")
        repo.count_active_owners = AsyncMock(return_value=1)
        service = _create_tenant_service(repo)

        dto = UpdateMemberRoleRequest(role="ACCOUNTANT")
        with pytest.raises(ForbiddenError):
            await service.update_member_role(tid, target, dto, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_update_role_invalid_role_raises_bad_request(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        target = _uid()

        repo = MagicMock()
        service = _create_tenant_service(repo)

        dto = UpdateMemberRoleRequest(role="SUPERUSER")
        with pytest.raises(BadRequestError):
            await service.update_member_role(tid, target, dto, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_update_role_target_not_found(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        target = _uid()

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value=None)
        service = _create_tenant_service(repo)

        dto = UpdateMemberRoleRequest(role="ACCOUNTANT")
        with pytest.raises(NotFoundError):
            await service.update_member_role(tid, target, dto, uid)

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_update_role_success(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        target = _uid()
        now = datetime.now(UTC)

        repo = MagicMock()
        repo.get_user_role = AsyncMock(return_value="VIEWER")
        repo.count_active_owners = AsyncMock(return_value=2)
        repo.update_membership_role = AsyncMock(return_value=True)
        repo.list_tenant_members = AsyncMock(
            return_value=[
                TenantMemberRow(user_id=target, email="t@x.com", role="ACCOUNTANT", created_at=now),
            ]
        )
        audit = _FakeAuditClient()
        service = _create_tenant_service(repo, audit)

        dto = UpdateMemberRoleRequest(role="ACCOUNTANT")
        result = await service.update_member_role(tid, target, dto, uid)

        assert result.user_id == str(target)
        assert result.role == "ACCOUNTANT"
        assert len(audit.entries) == 1
        entry = audit.entries[0]
        assert entry.action == "ROLE_CHANGED"
        assert entry.entity_type == "tenant"
        assert entry.user_id == uid
        assert entry.changes == {"user_id": str(target), "from": "VIEWER", "to": "ACCOUNTANT"}

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_update_role_permission_denied(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        """Viewer cannot update roles."""
        mock_eval.return_value = _denied("permission_denied")
        repo = MagicMock()
        service = _create_tenant_service(repo)

        dto = UpdateMemberRoleRequest(role="ACCOUNTANT")
        with pytest.raises(ForbiddenError):
            await service.update_member_role(
                sample_tenant_id,
                _uid(),
                dto,
                sample_user_id,
            )


# ---------------------------------------------------------------------------
# list_members
# ---------------------------------------------------------------------------


class TestListMembers:
    """Tests for TenantService.list_members()."""

    @patch(MOCK_EVAL_PATH, new_callable=AsyncMock)
    async def test_list_members_returns_mapped_results(
        self, mock_eval: AsyncMock, sample_tenant_id: TenantId, sample_user_id: UserId
    ) -> None:
        mock_eval.return_value = _allowed(sample_user_id, sample_tenant_id)
        tid = sample_tenant_id
        uid = sample_user_id
        u2 = _uid()
        now = datetime.now(UTC)

        repo = MagicMock()
        repo.list_tenant_members = AsyncMock(
            return_value=[
                TenantMemberRow(user_id=uid, email="owner@x.com", role="OWNER", created_at=now),
                TenantMemberRow(user_id=u2, email="viewer@x.com", role="VIEWER", created_at=now),
            ]
        )
        service = _create_tenant_service(repo)

        results = await service.list_members(tid, uid)

        assert len(results) == 2
        by_email = {r.email: r for r in results}
        assert by_email["owner@x.com"].role == "OWNER"
        assert by_email["viewer@x.com"].role == "VIEWER"
        assert by_email["viewer@x.com"].user_id == str(u2)
