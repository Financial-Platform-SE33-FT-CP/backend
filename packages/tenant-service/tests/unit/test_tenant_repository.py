"""Unit tests for SqlAlchemyTenantRepository."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from accounting_shared.database import Base as SharedBase
from accounting_shared.types import TenantId, UserId
from auth_service.modules.auth.infrastructure.models import Base as AuthBase, UserModel
from tenant_service.modules.tenants.domain.entities import Tenant, TenantUser
from tenant_service.modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine(tmp_path: object) -> AsyncGenerator[object, None]:
    path = tmp_path / "repo_test.sqlite"
    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    eng = create_async_engine(url)
    async with eng.begin() as conn:
        await conn.run_sync(AuthBase.metadata.create_all)
        await conn.run_sync(SharedBase.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: object) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as s:
        yield s
        await s.rollback()


@pytest.fixture
def repo(session: AsyncSession) -> SqlAlchemyTenantRepository:
    return SqlAlchemyTenantRepository(session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> UserId:
    return UserId(uuid.uuid4())


def _tid() -> TenantId:
    return TenantId(uuid.uuid4())


def _make_tenant_domain(tid: TenantId, uid: UserId, **overrides: object) -> Tenant:
    now = datetime.now(UTC)
    return Tenant(
        id=tid,
        name=overrides.get("name", "Test Co"),
        uen=overrides.get("uen", "202400001A"),
        base_currency=overrides.get("base_currency", "SGD"),
        gst_registered=overrides.get("gst_registered", False),
        financial_year_start_month=overrides.get("fy_month", 1),
        financial_year_start_day=overrides.get("fy_day", 1),
        status=overrides.get("status", "active"),
        created_by_user_id=uid,
        created_at=now,
        updated_at=now,
    )


def _make_tenant_user(
    tid: TenantId,
    uid: UserId,
    role: str = "OWNER",
    status: str = "active",
) -> TenantUser:
    now = datetime.now(UTC)
    return TenantUser(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        user_id=uid,
        role=role,
        status=status,
        created_at=now,
        updated_at=now,
    )


async def _insert_user(session: AsyncSession, uid: UserId, email: str) -> None:
    """Insert a user row needed for join-based queries."""
    session.add(
        UserModel(
            id=uid,
            email=email,
            hashed_password="dummy",
            full_name="Test",
            email_verified=True,
            is_active=True,
            failed_login_attempts=0,
            locked_until=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# create / get_by_id / tenant_exists
# ---------------------------------------------------------------------------


class TestCreateAndGet:
    """Tests for create(), get_by_id(), tenant_exists()."""

    async def test_create_and_get_by_id(self, repo: SqlAlchemyTenantRepository) -> None:
        uid = _uid()
        tid = _tid()
        tenant = _make_tenant_domain(tid, uid, name="Acme")

        created = await repo.create(tenant)
        assert created.id == tid
        assert created.name == "Acme"

        fetched = await repo.get_by_id(tid)
        assert fetched is not None
        assert fetched.id == tid
        assert fetched.name == "Acme"
        assert fetched.base_currency == "SGD"

    async def test_get_by_id_not_found(self, repo: SqlAlchemyTenantRepository) -> None:
        result = await repo.get_by_id(_tid())
        assert result is None

    async def test_tenant_exists_true(self, repo: SqlAlchemyTenantRepository) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        assert await repo.tenant_exists(tid) is True

    async def test_tenant_exists_false(self, repo: SqlAlchemyTenantRepository) -> None:
        assert await repo.tenant_exists(_tid()) is False


# ---------------------------------------------------------------------------
# add_user / get_user_role / remove_user / update_membership_role
# ---------------------------------------------------------------------------


class TestMembership:
    """Tests for membership CRUD operations."""

    async def test_add_user_and_get_role(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        tu = _make_tenant_user(tid, uid, role="OWNER")
        await repo.add_user(tu)

        role = await repo.get_user_role(tid, uid)
        assert role == "OWNER"

    async def test_get_user_role_inactive_returns_none(
        self,
        repo: SqlAlchemyTenantRepository,
        session: AsyncSession,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        tu = _make_tenant_user(tid, uid, role="OWNER", status="inactive")
        await repo.add_user(tu)

        role = await repo.get_user_role(tid, uid)
        assert role is None

    async def test_get_user_role_no_membership(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        assert await repo.get_user_role(tid, uid) is None

    async def test_remove_user(
        self,
        repo: SqlAlchemyTenantRepository,
        session: AsyncSession,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        await repo.add_user(_make_tenant_user(tid, uid))

        await repo.remove_user(tid, uid)
        assert await repo.get_user_role(tid, uid) is None

    async def test_remove_user_nonexistent_noop(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        """Removing a non-existent user should not raise."""
        await repo.remove_user(_tid(), _uid())

    async def test_update_membership_role_success(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        await repo.add_user(_make_tenant_user(tid, uid, role="VIEWER"))

        ok = await repo.update_membership_role(tid, uid, "ACCOUNTANT")
        assert ok is True
        assert await repo.get_user_role(tid, uid) == "ACCOUNTANT"

    async def test_update_membership_role_nonexistent_returns_false(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        ok = await repo.update_membership_role(_tid(), _uid(), "ACCOUNTANT")
        assert ok is False


# ---------------------------------------------------------------------------
# count_active_owners
# ---------------------------------------------------------------------------


class TestCountActiveOwners:
    """Tests for count_active_owners()."""

    async def test_count_owners(self, repo: SqlAlchemyTenantRepository) -> None:
        uid1, uid2, uid3 = _uid(), _uid(), _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid1))
        await repo.add_user(_make_tenant_user(tid, uid1, role="OWNER"))
        await repo.add_user(_make_tenant_user(tid, uid2, role="OWNER"))
        await repo.add_user(_make_tenant_user(tid, uid3, role="OWNER", status="inactive"))
        await repo.add_user(_make_tenant_user(_uid(), _uid(), role="VIEWER"))  # other tenant noise

        count = await repo.count_active_owners(tid)
        assert count == 2

    async def test_count_owners_zero(self, repo: SqlAlchemyTenantRepository) -> None:
        assert await repo.count_active_owners(_tid()) == 0


# ---------------------------------------------------------------------------
# list_tenant_members / find_user_id_by_email
# ---------------------------------------------------------------------------


class TestMemberListing:
    """Tests for list_tenant_members() and find_user_id_by_email()."""

    async def test_list_tenant_members(
        self,
        repo: SqlAlchemyTenantRepository,
        session: AsyncSession,
    ) -> None:
        uid1, uid2 = _uid(), _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid1))
        await _insert_user(session, uid1, "bob@example.com")
        await _insert_user(session, uid2, "alice@example.com")
        await repo.add_user(_make_tenant_user(tid, uid1, role="OWNER"))
        await repo.add_user(_make_tenant_user(tid, uid2, role="VIEWER"))

        rows = await repo.list_tenant_members(tid)
        assert len(rows) == 2
        emails = [r.email for r in rows]
        # Should be sorted by email
        assert emails == ["alice@example.com", "bob@example.com"]

    async def test_find_user_id_by_email_case_insensitive(
        self,
        repo: SqlAlchemyTenantRepository,
        session: AsyncSession,
    ) -> None:
        uid = _uid()
        await _insert_user(session, uid, "Test@Example.COM")

        found = await repo.find_user_id_by_email("test@example.com")
        assert found == uid

    async def test_find_user_id_by_email_not_found(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        assert await repo.find_user_id_by_email("noone@example.com") is None


# ---------------------------------------------------------------------------
# list_for_active_user / get_for_active_member
# ---------------------------------------------------------------------------


class TestUserTenants:
    """Tests for list_for_active_user() and get_for_active_member()."""

    async def test_list_for_active_user(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        uid = _uid()
        tid1, tid2, tid3 = _tid(), _tid(), _tid()

        await repo.create(_make_tenant_domain(tid1, uid, name="A"))
        await repo.create(_make_tenant_domain(tid2, uid, name="B"))
        await repo.create(_make_tenant_domain(tid3, uid, name="C"))
        await repo.add_user(_make_tenant_user(tid1, uid, role="OWNER"))
        await repo.add_user(_make_tenant_user(tid2, uid, role="VIEWER"))
        await repo.add_user(_make_tenant_user(tid3, uid, role="OWNER", status="inactive"))

        results = await repo.list_for_active_user(uid)
        assert len(results) == 2
        names = {t.name for t, _ in results}
        assert names == {"A", "B"}

    async def test_get_for_active_member(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        await repo.add_user(_make_tenant_user(tid, uid, role="OWNER"))

        t = await repo.get_for_active_member(tid, uid)
        assert t is not None
        assert t.id == tid

    async def test_get_for_active_member_inactive(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        await repo.add_user(_make_tenant_user(tid, uid, role="OWNER", status="inactive"))

        t = await repo.get_for_active_member(tid, uid)
        assert t is None


# ---------------------------------------------------------------------------
# seed_default_coa / list_coa_for_tenant
# ---------------------------------------------------------------------------


class TestSeedDefaultCoa:
    """Tests for seed_default_coa() and list_coa_for_tenant()."""

    async def test_seed_default_coa(
        self,
        repo: SqlAlchemyTenantRepository,
    ) -> None:
        uid = _uid()
        tid = _tid()
        await repo.create(_make_tenant_domain(tid, uid))
        await repo.seed_default_coa(tid)

        rows = await repo.list_coa_for_tenant(tid)
        assert len(rows) == 24
        codes = {r.code for r in rows}
        assert "1000" in codes
        assert "6900" in codes
        # All should be system defaults
        assert all(r.is_system_default for r in rows)
        # All belong to this tenant
        assert all(r.tenant_id == str(tid) for r in rows)
