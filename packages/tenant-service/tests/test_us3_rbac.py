"""US-3 RBAC: roles, permissions, membership APIs, audit deny logging, internal authz."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from accounting_shared.database import Base as SharedBase
from audit_service.modules.audit.infrastructure.models import AuditLogModel  # noqa: F401
from auth_service.modules.auth.infrastructure.models import Base as AuthBase, UserModel
from coa_service.modules.coa.infrastructure.models import AccountModel  # noqa: F401
from tenant_service.deps import get_async_session
from tenant_service.main import create_app
from tenant_service.modules.tenants.infrastructure.models import (  # noqa: F401
    TenantModel,
    TenantUserModel,
)

JWT_SECRET = "us3-test-jwt-secret"
DATABASE_URL_ENV = "DATABASE_URL"
INTERNAL_TOKEN = "us3-internal-test-token"


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


async def _create_user(session: AsyncSession, *, user_id: uuid.UUID, email: str) -> None:
    u = UserModel(
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
    session.add(u)
    await session.flush()


def _reset_tenant_deps() -> None:
    import tenant_service.deps as d

    d._settings = None  # type: ignore[attr-defined]
    d._engine = None  # type: ignore[attr-defined]
    d._session_factory = None  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def engine(tmp_path: object) -> AsyncGenerator[object, None]:
    path = tmp_path / "us3.sqlite"
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
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    url = str(engine.url)
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", INTERNAL_TOKEN)
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


async def _fresh_tenant(client: AsyncClient, session_factory: object, owner: uuid.UUID) -> uuid.UUID:
    async with session_factory() as s:  # type: ignore[misc]
        await _create_user(s, user_id=owner, email=f"{owner.hex[:8]}@x.com")
        await s.commit()
    r = await client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        json={
            "name": "Co",
            "base_currency": "SGD",
            "financial_year_start_month": 1,
            "financial_year_start_day": 1,
        },
    )
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


@pytest.mark.asyncio
async def test_creator_is_owner(session_factory: object, client: AsyncClient) -> None:
    owner = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:  # type: ignore[misc]
        tu = (
            await s.execute(
                select(TenantUserModel).where(
                    TenantUserModel.tenant_id == tid,
                    TenantUserModel.user_id == owner,
                )
            )
        ).scalar_one()
        assert tu.role == "OWNER"


@pytest.mark.asyncio
async def test_owner_can_list_members(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)

    r2 = await client.get(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert len(data) == 1
    assert data[0]["user_id"] == str(owner)
    assert data[0]["role"] == "OWNER"


@pytest.mark.asyncio
async def test_accountant_cannot_list_members_audit(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    accountant = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)

    async with session_factory() as s:
        await _create_user(s, user_id=accountant, email="acc@x.com")
        s.add(
            TenantUserModel(
                id=uuid.uuid4(),
                tenant_id=tid,
                user_id=accountant,
                role="ACCOUNTANT",
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.commit()

    rdeny = await client.get(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(accountant)}"},
    )
    assert rdeny.status_code == 403

    async with session_factory() as s:
        logs = (await s.execute(select(AuditLogModel))).scalars().all()
    rbac_logs = [x for x in logs if x.action == "RBAC_DENIED"]
    assert len(rbac_logs) >= 1
    assert rbac_logs[-1].changes is not None
    assert rbac_logs[-1].changes.get("result") == "denied"
    assert rbac_logs[-1].changes.get("attempted_action", "").startswith("GET ")


@pytest.mark.asyncio
async def test_me_role_returns_permissions(
    client: AsyncClient,
    session_factory: object,
) -> None:
    uid = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, uid)
    mr = await client.get(
        f"/api/v1/tenants/{tid}/me/role",
        headers={"Authorization": f"Bearer {_encode_token(uid)}"},
    )
    assert mr.status_code == 200
    body = mr.json()
    assert body["tenant_id"] == str(tid)
    assert body["user_id"] == str(uid)
    assert body["role"] == "OWNER"
    assert "tenant:read" in body["permissions"]
    assert "tenant:member:add" in body["permissions"]
    assert "coa:read" in body["permissions"]


@pytest.mark.asyncio
async def test_last_owner_demote_forbidden(client: AsyncClient, session_factory: object) -> None:
    uid = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, uid)

    bad = await client.patch(
        f"/api/v1/tenants/{tid}/members/{uid}/role",
        headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        json={"role": "ACCOUNTANT"},
    )
    assert bad.status_code == 403


@pytest.mark.asyncio
async def test_non_member_get_tenant_forbidden(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    a = uuid.uuid4()
    b = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, a)
    async with session_factory() as s:
        await _create_user(s, user_id=b, email="bb@x.com")
        await s.commit()

    r2 = await client.get(
        f"/api/v1/tenants/{tid}",
        headers={"Authorization": f"Bearer {_encode_token(b)}"},
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_invite_invalid_role_400(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    uid = uuid.uuid4()
    invitee = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, uid)
    async with session_factory() as s:
        await _create_user(s, user_id=invitee, email="new@x.com")
        await s.commit()

    bad = await client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        json={"user_id": str(invitee), "role": "SUPERUSER"},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_unauthenticated_401(client: AsyncClient) -> None:
    r = await client.get(f"/api/v1/tenants/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_owner_can_add_member(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    new_u = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=new_u, email="join@x.com")
        await s.commit()
    r = await client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        json={"user_id": str(new_u), "role": "VIEWER"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "VIEWER"


@pytest.mark.asyncio
async def test_owner_can_invite_member_by_email_case_insensitive(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    new_u = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=new_u, email="Join@Example.COM")
        await s.commit()
    r = await client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        json={"email": "join@example.com", "role": "VIEWER"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["user_id"] == str(new_u)


@pytest.mark.asyncio
async def test_accountant_cannot_add_member(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    accountant = uuid.uuid4()
    victim = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=accountant, email="acc2@x.com")
        await _create_user(s, user_id=victim, email="vic@x.com")
        s.add(
            TenantUserModel(
                id=uuid.uuid4(),
                tenant_id=tid,
                user_id=accountant,
                role="ACCOUNTANT",
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.commit()
    r = await client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(accountant)}"},
        json={"user_id": str(victim), "role": "VIEWER"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_update_member_role(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=other, email="oth@x.com")
        s.add(
            TenantUserModel(
                id=uuid.uuid4(),
                tenant_id=tid,
                user_id=other,
                role="VIEWER",
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.commit()
    r = await client.patch(
        f"/api/v1/tenants/{tid}/members/{other}/role",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        json={"role": "ACCOUNTANT"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "ACCOUNTANT"


@pytest.mark.asyncio
async def test_accountant_cannot_update_role(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    accountant = uuid.uuid4()
    viewer = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=accountant, email="acc3@x.com")
        await _create_user(s, user_id=viewer, email="vw@x.com")
        for uid, role in [(accountant, "ACCOUNTANT"), (viewer, "VIEWER")]:
            s.add(
                TenantUserModel(
                    id=uuid.uuid4(),
                    tenant_id=tid,
                    user_id=uid,
                    role=role,
                    status="active",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        await s.commit()
    r = await client.patch(
        f"/api/v1/tenants/{tid}/members/{viewer}/role",
        headers={"Authorization": f"Bearer {_encode_token(accountant)}"},
        json={"role": "ACCOUNTANT"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_read_coa_forbidden_on_write(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    viewer = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=viewer, email="view@x.com")
        s.add(
            TenantUserModel(
                id=uuid.uuid4(),
                tenant_id=tid,
                user_id=viewer,
                role="VIEWER",
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.commit()
    r_ok = await client.get(
        f"/api/v1/tenants/{tid}/coa",
        headers={"Authorization": f"Bearer {_encode_token(viewer)}"},
    )
    assert r_ok.status_code == 200
    r_deny = await client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(viewer)}"},
        json={"user_id": str(uuid.uuid4()), "role": "VIEWER"},
    )
    assert r_deny.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_membership_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    u2 = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=u2, email="dup@x.com")
        await s.commit()
    j = {"user_id": str(u2), "role": "VIEWER"}
    r1 = await client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        json=j,
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/v1/tenants/{tid}/members",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
        json=j,
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_last_owner_cannot_be_removed(
    client: AsyncClient,
    session_factory: object,
) -> None:
    owner = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    r = await client.delete(
        f"/api/v1/tenants/{tid}/members/{owner}",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_remove_non_owner_member(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    victim = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    async with session_factory() as s:
        await _create_user(s, user_id=victim, email="gone@x.com")
        s.add(
            TenantUserModel(
                id=uuid.uuid4(),
                tenant_id=tid,
                user_id=victim,
                role="VIEWER",
                status="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.commit()
    r = await client.delete(
        f"/api/v1/tenants/{tid}/members/{victim}",
        headers={"Authorization": f"Bearer {_encode_token(owner)}"},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_internal_authorization_check(
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    owner = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    hdrs = {"X-Internal-Token": INTERNAL_TOKEN}
    r_ok = await client.post(
        "/internal/authorization/check",
        headers=hdrs,
        json={
            "user_id": str(owner),
            "tenant_id": str(tid),
            "permission": "coa:update",
        },
    )
    assert r_ok.status_code == 200, r_ok.text
    body = r_ok.json()
    assert body["allowed"] is True
    assert body["role"] == "OWNER"

    r_deny = await client.post(
        "/internal/authorization/check",
        headers=hdrs,
        json={
            "user_id": str(uuid.uuid4()),
            "tenant_id": str(tid),
            "permission": "coa:read",
        },

    )
    assert r_deny.status_code == 200
    assert r_deny.json()["allowed"] is False
    assert r_deny.json()["reason"] == "not_member"


@pytest.mark.asyncio
async def test_internal_authorization_wrong_token(client: AsyncClient, session_factory: object) -> None:
    owner = uuid.uuid4()
    tid = await _fresh_tenant(client, session_factory, owner)
    r = await client.post(
        "/internal/authorization/check",
        headers={"X-Internal-Token": "wrong"},
        json={"user_id": str(owner), "tenant_id": str(tid), "permission": "coa:read"},
    )
    assert r.status_code == 401
