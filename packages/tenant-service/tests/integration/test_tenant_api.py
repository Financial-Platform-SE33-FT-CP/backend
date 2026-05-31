"""Integration tests for tenant API endpoints and portal router."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from accounting_shared.database import Base as SharedBase
from auth_service.modules.auth.infrastructure.models import Base as AuthBase, UserModel
from tenant_service.deps import get_async_session
from tenant_service.main import create_app

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

JWT_SECRET = "integration-test-jwt-secret"
INTERNAL_TOKEN = "integration-internal-token"
DATABASE_URL_ENV = "DATABASE_URL"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": "test@example.com",
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


async def _create_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
) -> None:
    session.add(
        UserModel(
            id=user_id,
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


def _reset_tenant_deps() -> None:
    import tenant_service.deps as d

    d._settings = None  # type: ignore[attr-defined]
    d._engine = None  # type: ignore[attr-defined]
    d._session_factory = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine(tmp_path: object) -> AsyncGenerator[object, None]:
    path = tmp_path / "integration.sqlite"
    url = f"sqlite+aiosqlite:///{path.as_posix()}"
    eng = create_async_engine(url)
    async with eng.begin() as conn:
        await conn.run_sync(AuthBase.metadata.create_all)
        await conn.run_sync(SharedBase.metadata.create_all)
    yield eng
    await eng.dispose()
    _reset_tenant_deps()


@pytest_asyncio.fixture
async def session_factory(
    engine: object,
    monkeypatch: object,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    url = str(engine.url)
    monkeypatch.setenv(DATABASE_URL_ENV, url)  # type: ignore[attr-defined]
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)  # type: ignore[attr-defined]
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", INTERNAL_TOKEN)  # type: ignore[attr-defined]
    _reset_tenant_deps()
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def app(session_factory: async_sessionmaker[AsyncSession]) -> object:
    application = create_app()

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    application.dependency_overrides[get_async_session] = _override_session
    return application


@pytest_asyncio.fixture
async def client(app: object) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),  # type: ignore[arg-type]
        base_url="http://test",
    ) as ac:
        yield ac


async def _seed_user(
    session_factory: async_sessionmaker[AsyncSession],
    uid: uuid.UUID,
    email: str,
) -> None:
    async with session_factory() as s:
        await _create_user(s, user_id=uid, email=email)
        await s.commit()


async def _create_tenant(
    client: AsyncClient,
    uid: uuid.UUID,
    name: str = "TestCo",
    **overrides: object,
) -> dict:
    """Create a tenant and return the JSON response body."""
    payload = {
        "name": name,
        "base_currency": overrides.get("currency", "SGD"),
        "financial_year_start_month": overrides.get("fy_month", 1),
        "financial_year_start_day": overrides.get("fy_day", 1),
    }
    if "uen" in overrides:
        payload["uen"] = overrides["uen"]
    if "gst" in overrides:
        payload["gst_registered"] = overrides["gst"]
    r = await client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        json=payload,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ===================================================================
# Tenant CRUD lifecycle
# ===================================================================


class TestTenantCrudLifecycle:
    """POST create → GET by id → GET list — full round-trip."""

    async def test_create_get_list(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "owner@example.com")

        # Create
        body = await _create_tenant(client, uid, name="Lifecycle Co", uen="202412345A")
        tid = body["id"]
        assert body["name"] == "Lifecycle Co"
        assert body["role"] == "OWNER"

        # Get by id
        r_get = await client.get(
            f"/api/v1/tenants/{tid}",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        )
        assert r_get.status_code == 200
        assert r_get.json()["name"] == "Lifecycle Co"
        assert r_get.json()["uen"] == "202412345A"

        # List
        r_list = await client.get(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        )
        assert r_list.status_code == 200
        names = {t["name"] for t in r_list.json()}
        assert "Lifecycle Co" in names


class TestGetTenantErrors:
    """Edge cases for GET /tenants/{id}."""

    async def test_get_nonexistent_tenant_404(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@example.com")
        r = await client.get(
            f"/api/v1/tenants/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        )
        assert r.status_code == 404

    async def test_get_tenant_non_member_403(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        outsider = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@example.com")
        await _seed_user(session_factory, outsider, "out@example.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.get(
            f"/api/v1/tenants/{tid}",
            headers={"Authorization": f"Bearer {_encode_token(outsider)}"},
        )
        assert r.status_code == 403

    async def test_get_tenant_unauthenticated_401(self, client: AsyncClient) -> None:
        r = await client.get(f"/api/v1/tenants/{uuid.uuid4()}")
        assert r.status_code == 401


# ===================================================================
# Member management full flow
# ===================================================================


class TestMemberManagementFlow:
    """Invite → list → update role → remove — full round-trip."""

    async def test_invite_list_update_remove(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        member = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@example.com")
        await _seed_user(session_factory, member, "mem@example.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        # Invite by user_id
        r_invite = await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"user_id": str(member), "role": "VIEWER"},
        )
        assert r_invite.status_code == 201, r_invite.text
        assert r_invite.json()["role"] == "VIEWER"

        # List members
        r_list = await client.get(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        )
        assert r_list.status_code == 200
        member_ids = {m["user_id"] for m in r_list.json()}
        assert str(member) in member_ids
        assert str(owner) in member_ids

        # Update role
        r_patch = await client.patch(
            f"/api/v1/tenants/{tid}/members/{member}/role",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"role": "ACCOUNTANT"},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["role"] == "ACCOUNTANT"

        # Remove member
        r_del = await client.delete(
            f"/api/v1/tenants/{tid}/members/{member}",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        )
        assert r_del.status_code == 204

        # Verify removal
        r_list2 = await client.get(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        )
        member_ids2 = {m["user_id"] for m in r_list2.json()}
        assert str(member) not in member_ids2
        assert str(owner) in member_ids2


class TestInviteMemberEdgeCases:
    """Additional invite member scenarios."""

    async def test_invite_by_email(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        member = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, member, "Join@Example.COM")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"email": "join@example.com", "role": "VIEWER"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["user_id"] == str(member)

    async def test_invite_nonexistent_email_404(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"email": "ghost@example.com", "role": "VIEWER"},
        )
        assert r.status_code == 404

    async def test_invite_duplicate_409(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        member = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, member, "mem@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        payload = {"user_id": str(member), "role": "VIEWER"}
        r1 = await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json=payload,
        )
        assert r1.status_code == 201

        r2 = await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json=payload,
        )
        assert r2.status_code == 409

    async def test_invite_invalid_role_400(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        member = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, member, "mem@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"user_id": str(member), "role": "SUPERUSER"},
        )
        assert r.status_code == 400

    async def test_invite_missing_target_422(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        """Neither user_id nor email provided."""
        owner = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"role": "VIEWER"},
        )
        assert r.status_code == 422


# ===================================================================
# Role update edge cases
# ===================================================================


class TestUpdateMemberRoleEdgeCases:
    """Additional role update scenarios."""

    async def test_update_role_nonexistent_member_404(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.patch(
            f"/api/v1/tenants/{tid}/members/{uuid.uuid4()}/role",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"role": "ACCOUNTANT"},
        )
        assert r.status_code == 404

    async def test_update_role_last_owner_demote_403(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.patch(
            f"/api/v1/tenants/{tid}/members/{owner}/role",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"role": "ACCOUNTANT"},
        )
        assert r.status_code == 403

    async def test_update_role_non_owner_forbidden(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        """Accountant cannot update roles."""
        owner = uuid.uuid4()
        accountant = uuid.uuid4()
        viewer = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, accountant, "acc@x.com")
        await _seed_user(session_factory, viewer, "view@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        # Add accountant and viewer
        for uid, role in [(accountant, "ACCOUNTANT"), (viewer, "VIEWER")]:
            await client.post(
                f"/api/v1/tenants/{tid}/members",
                headers={"Authorization": f"Bearer {_encode_token(owner)}"},
                json={"user_id": str(uid), "role": role},
            )

        r = await client.patch(
            f"/api/v1/tenants/{tid}/members/{viewer}/role",
            headers={"Authorization": f"Bearer {_encode_token(accountant)}"},
            json={"role": "ACCOUNTANT"},
        )
        assert r.status_code == 403


# ===================================================================
# Remove member edge cases
# ===================================================================


class TestRemoveMemberEdgeCases:
    """Additional remove member scenarios."""

    async def test_remove_nonexistent_member_404(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.delete(
            f"/api/v1/tenants/{tid}/members/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        )
        assert r.status_code == 404

    async def test_remove_last_owner_403(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.delete(
            f"/api/v1/tenants/{tid}/members/{owner}",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        )
        assert r.status_code == 403

    async def test_remove_member_by_non_owner_forbidden(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        """Viewer cannot remove members."""
        owner = uuid.uuid4()
        viewer = uuid.uuid4()
        target = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, viewer, "view@x.com")
        await _seed_user(session_factory, target, "tgt@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        for uid, role in [(viewer, "VIEWER"), (target, "VIEWER")]:
            await client.post(
                f"/api/v1/tenants/{tid}/members",
                headers={"Authorization": f"Bearer {_encode_token(owner)}"},
                json={"user_id": str(uid), "role": role},
            )

        r = await client.delete(
            f"/api/v1/tenants/{tid}/members/{target}",
            headers={"Authorization": f"Bearer {_encode_token(viewer)}"},
        )
        assert r.status_code == 403


# ===================================================================
# Multi-tenant isolation
# ===================================================================


class TestMultiTenantIsolation:
    """Comprehensive cross-tenant access tests."""

    async def test_cross_tenant_full_isolation(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        await _seed_user(session_factory, user_a, "a@x.com")
        await _seed_user(session_factory, user_b, "b@x.com")

        body_a = await _create_tenant(client, user_a, name="TenantA")
        body_b = await _create_tenant(client, user_b, name="TenantB")
        tid_a = body_a["id"]
        tid_b = body_b["id"]

        hdr_a = {"Authorization": f"Bearer {_encode_token(user_a)}"}
        hdr_b = {"Authorization": f"Bearer {_encode_token(user_b)}"}

        # A cannot access B's tenant
        assert (await client.get(f"/api/v1/tenants/{tid_b}", headers=hdr_a)).status_code == 403
        assert (await client.get(f"/api/v1/tenants/{tid_b}/coa", headers=hdr_a)).status_code == 403
        assert (
            await client.get(f"/api/v1/tenants/{tid_b}/me/role", headers=hdr_a)
        ).status_code == 403
        assert (
            await client.get(f"/api/v1/tenants/{tid_b}/members", headers=hdr_a)
        ).status_code == 403

        # B cannot access A's tenant
        assert (await client.get(f"/api/v1/tenants/{tid_a}", headers=hdr_b)).status_code == 403
        assert (await client.get(f"/api/v1/tenants/{tid_a}/coa", headers=hdr_b)).status_code == 403
        assert (
            await client.get(f"/api/v1/tenants/{tid_a}/me/role", headers=hdr_b)
        ).status_code == 403
        assert (
            await client.get(f"/api/v1/tenants/{tid_a}/members", headers=hdr_b)
        ).status_code == 403

        # Each can access their own
        assert (await client.get(f"/api/v1/tenants/{tid_a}", headers=hdr_a)).status_code == 200
        assert (await client.get(f"/api/v1/tenants/{tid_a}/coa", headers=hdr_a)).status_code == 200
        assert (
            await client.get(f"/api/v1/tenants/{tid_a}/me/role", headers=hdr_a)
        ).status_code == 200
        assert (
            await client.get(f"/api/v1/tenants/{tid_a}/members", headers=hdr_a)
        ).status_code == 200

        assert (await client.get(f"/api/v1/tenants/{tid_b}", headers=hdr_b)).status_code == 200
        assert (await client.get(f"/api/v1/tenants/{tid_b}/coa", headers=hdr_b)).status_code == 200
        assert (
            await client.get(f"/api/v1/tenants/{tid_b}/me/role", headers=hdr_b)
        ).status_code == 200
        assert (
            await client.get(f"/api/v1/tenants/{tid_b}/members", headers=hdr_b)
        ).status_code == 200


# ===================================================================
# me/role endpoint
# ===================================================================


class TestMeRole:
    """Tests for GET /tenants/{id}/me/role."""

    async def test_me_role_owner_full_permissions(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "own@x.com")
        body = await _create_tenant(client, uid)
        tid = body["id"]

        r = await client.get(
            f"/api/v1/tenants/{tid}/me/role",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "OWNER"
        assert "tenant:read" in data["permissions"]
        assert "tenant:member:add" in data["permissions"]
        assert "coa:read" in data["permissions"]
        assert "coa:create" in data["permissions"]

    async def test_me_role_non_member_403(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        outsider = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, outsider, "out@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.get(
            f"/api/v1/tenants/{tid}/me/role",
            headers={"Authorization": f"Bearer {_encode_token(outsider)}"},
        )
        assert r.status_code == 403


# ===================================================================
# Tenant creation validation
# ===================================================================


class TestCreateTenantValidation:
    """Validation edge cases for POST /tenants."""

    async def test_create_missing_name_422(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@x.com")
        r = await client.post(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
            json={
                "base_currency": "SGD",
                "financial_year_start_month": 1,
                "financial_year_start_day": 1,
            },
        )
        assert r.status_code == 422

    async def test_create_unsupported_currency_422(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@x.com")
        r = await client.post(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
            json={
                "name": "Bad",
                "base_currency": "ZZZ",
                "financial_year_start_month": 1,
                "financial_year_start_day": 1,
            },
        )
        assert r.status_code == 422


# ===================================================================
# Internal authorization endpoint
# ===================================================================


class TestInternalAuthorization:
    """Tests for POST /internal/authorization/check."""

    async def test_internal_check_allowed(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@x.com")
        body = await _create_tenant(client, uid)
        tid = body["id"]

        r = await client.post(
            "/internal/authorization/check",
            headers={"X-Internal-Token": INTERNAL_TOKEN},
            json={
                "user_id": str(uid),
                "tenant_id": tid,
                "permission": "coa:read",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["allowed"] is True
        assert data["role"] == "OWNER"

    async def test_internal_check_denied_not_member(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@x.com")
        body = await _create_tenant(client, uid)
        tid = body["id"]

        r = await client.post(
            "/internal/authorization/check",
            headers={"X-Internal-Token": INTERNAL_TOKEN},
            json={
                "user_id": str(uuid.uuid4()),
                "tenant_id": tid,
                "permission": "coa:read",
            },
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is False
        assert r.json()["reason"] == "not_member"

    async def test_internal_check_wrong_token_401(self, client: AsyncClient) -> None:
        r = await client.post(
            "/internal/authorization/check",
            headers={"X-Internal-Token": "wrong"},
            json={
                "user_id": str(uuid.uuid4()),
                "tenant_id": str(uuid.uuid4()),
                "permission": "coa:read",
            },
        )
        assert r.status_code == 401


# ===================================================================
# Portal router endpoints
# ===================================================================


class TestPortalCreateTenant:
    """Tests for POST /tenants/ (portal)."""

    async def test_portal_create_tenant(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@x.com")

        r = await client.post(
            "/tenants/",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
            json={
                "name": "Portal Co",
                "slug": "portal-co",
                "base_currency": "SGD",
                "fiscal_year_start_mmdd": "04-01",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "Portal Co"
        assert body["is_active"] is True
        assert body["base_currency"] == "SGD"
        assert body["current_user_role"] == "admin"  # portal uses lowercase roles


class TestPortalListTenants:
    """Tests for GET /tenants/ (portal)."""

    async def test_portal_list_tenants(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@x.com")
        await _create_tenant(client, uid, name="Co1")
        await _create_tenant(client, uid, name="Co2")

        r = await client.get(
            "/tenants/",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        )
        assert r.status_code == 200
        names = {t["name"] for t in r.json()}
        assert names == {"Co1", "Co2"}


class TestPortalMemberManagement:
    """Tests for portal member endpoints (/tenants/{id}/users)."""

    async def test_portal_list_members(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        uid = uuid.uuid4()
        await _seed_user(session_factory, uid, "u@x.com")
        body = await _create_tenant(client, uid)
        tid = body["id"]

        r = await client.get(
            f"/tenants/{tid}/users",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["role"] == "admin"

    async def test_portal_invite_member_by_email(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        member = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, member, "New@Example.COM")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        r = await client.post(
            f"/tenants/{tid}/users",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"email": "new@example.com", "role": "manager"},
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["user_id"] == str(member)
        assert data["role"] == "manager"

    async def test_portal_remove_member(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: AsyncClient,
    ) -> None:
        owner = uuid.uuid4()
        member = uuid.uuid4()
        await _seed_user(session_factory, owner, "own@x.com")
        await _seed_user(session_factory, member, "mem@x.com")
        body = await _create_tenant(client, owner)
        tid = body["id"]

        # Add member first
        await client.post(
            f"/api/v1/tenants/{tid}/members",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
            json={"user_id": str(member), "role": "VIEWER"},
        )

        # Remove via portal
        r = await client.delete(
            f"/tenants/{tid}/users/{member}",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        )
        assert r.status_code == 204

        # Verify removal
        r_list = await client.get(
            f"/tenants/{tid}/users",
            headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        )
        user_ids = {m["user_id"] for m in r_list.json()}
        assert str(member) not in user_ids
