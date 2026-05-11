"""Integration tests for US-2 tenant creation, isolation, COA seed, and transactions."""

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
from auth_service.modules.auth.infrastructure.models import Base as AuthBase, UserModel
from coa_service.modules.coa.infrastructure.models import AccountModel  # noqa: F401
from tenant_service.deps import get_async_session
from tenant_service.main import create_app
from tenant_service.modules.tenants.infrastructure.models import (  # noqa: F401
    TenantModel,
    TenantUserModel,
)
from audit_service.modules.audit.infrastructure.models import AuditLogModel  # noqa: F401


JWT_SECRET = "us2-test-jwt-secret"
DATABASE_URL_ENV = "DATABASE_URL"


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
async def engine(
    tmp_path: object,
) -> AsyncGenerator[object, None]:
    path = tmp_path / "db.sqlite"
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


@pytest.mark.asyncio
async def test_create_tenant_success(
    app: object,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    uid = uuid.uuid4()
    async with session_factory() as s:
        await _create_user(s, user_id=uid, email="owner@example.com")
        await s.commit()

    token = _encode_token(uid)
    r = await client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Acme Pte Ltd",
            "uen": "202400001A",
            "base_currency": "SGD",
            "gst_registered": True,
            "financial_year_start_month": 1,
            "financial_year_start_day": 1,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Acme Pte Ltd"
    assert body["role"] == "owner"
    assert body["base_currency"] == "SGD"
    tid = uuid.UUID(body["id"])

    async with session_factory() as s:
        t = (await s.execute(select(TenantModel).where(TenantModel.id == tid))).scalar_one()
        assert t.name == "Acme Pte Ltd"
        assert t.created_by_user_id == uid
        tu = (
            await s.execute(
                select(TenantUserModel).where(
                    TenantUserModel.tenant_id == tid,
                    TenantUserModel.user_id == uid,
                )
            )
        ).scalar_one()
        assert tu.role == "owner"
        coa_count = (
            await s.execute(select(AccountModel).where(AccountModel.tenant_id == tid))
        ).scalars().all()
        assert len(coa_count) == 24
        logs = (await s.execute(select(AuditLogModel).where(AuditLogModel.tenant_id == tid))).scalars().all()
        assert len(logs) == 1
        assert logs[0].action == "TENANT_CREATED"
        assert logs[0].entity_type == "tenant"
        assert logs[0].entity_id == str(tid)
        assert logs[0].user_id == uid


@pytest.mark.asyncio
async def test_create_tenant_requires_auth(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tenants",
        json={
            "name": "X",
            "base_currency": "SGD",
            "financial_year_start_month": 4,
            "financial_year_start_day": 1,
        },
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_tenant_validation_currency(
    app: object,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    uid = uuid.uuid4()
    async with session_factory() as s:
        await _create_user(s, user_id=uid, email="v@example.com")
        await s.commit()
    token = _encode_token(uid)
    r = await client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Bad",
            "base_currency": "JPY",
            "financial_year_start_month": 1,
            "financial_year_start_day": 1,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_tenants_isolation(
    app: object,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    async with session_factory() as s:
        await _create_user(s, user_id=user_a, email="a@example.com")
        await _create_user(s, user_id=user_b, email="b@example.com")
        await s.commit()

    async def _create_company(uid: uuid.UUID, name: str) -> None:
        rs = await client.post(
            "/api/v1/tenants",
            headers={"Authorization": f"Bearer {_encode_token(uid)}"},
            json={
                "name": name,
                "base_currency": "SGD",
                "financial_year_start_month": 1,
                "financial_year_start_day": 1,
            },
        )
        assert rs.status_code == 201, rs.text

    await _create_company(user_a, "Company A")
    await _create_company(user_b, "Company B")

    ra = await client.get(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {_encode_token(user_a)}"},
    )
    assert ra.status_code == 200
    names_a = {x["name"] for x in ra.json()}
    assert names_a == {"Company A"}

    rb = await client.get(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {_encode_token(user_b)}"},
    )
    assert {x["name"] for x in rb.json()} == {"Company B"}


@pytest.mark.asyncio
async def test_get_tenant_isolation(
    app: object,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    async with session_factory() as s:
        await _create_user(s, user_id=user_a, email="ga@example.com")
        await _create_user(s, user_id=user_b, email="gb@example.com")
        await s.commit()

    r = await client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {_encode_token(user_a)}"},
        json={
            "name": "Secret Co",
            "base_currency": "SGD",
            "financial_year_start_month": 1,
            "financial_year_start_day": 1,
        },
    )
    tenant_id = r.json()["id"]

    r403 = await client.get(
        f"/api/v1/tenants/{tenant_id}",
        headers={"Authorization": f"Bearer {_encode_token(user_b)}"},
    )
    assert r403.status_code == 404


@pytest.mark.asyncio
async def test_get_coa_isolation(
    app: object,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    async with session_factory() as s:
        await _create_user(s, user_id=user_a, email="ca@example.com")
        await _create_user(s, user_id=user_b, email="cb@example.com")
        await s.commit()

    r = await client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {_encode_token(user_a)}"},
        json={
            "name": "COA Co",
            "base_currency": "SGD",
            "financial_year_start_month": 1,
            "financial_year_start_day": 1,
        },
    )
    tenant_id = r.json()["id"]

    rdeny = await client.get(
        f"/api/v1/tenants/{tenant_id}/coa",
        headers={"Authorization": f"Bearer {_encode_token(user_b)}"},
    )
    assert rdeny.status_code == 404

    rok = await client.get(
        f"/api/v1/tenants/{tenant_id}/coa",
        headers={"Authorization": f"Bearer {_encode_token(user_a)}"},
    )
    assert rok.status_code == 200
    codes = {a["code"] for a in rok.json()}
    assert "1000" in codes
    assert len(codes) == 24


@pytest.mark.asyncio
async def test_transaction_rollback_on_seed_failure(
    app: object,
    session_factory: async_sessionmaker[AsyncSession],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tenant_service.modules.tenants.infrastructure import repository as repo_mod

    uid = uuid.uuid4()
    async with session_factory() as s:
        await _create_user(s, user_id=uid, email="rb@example.com")
        await s.commit()

    async def _boom(_self: object, _tenant_id: object) -> None:
        msg = "simulated seed failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(repo_mod.SqlAlchemyTenantRepository, "seed_default_coa", _boom)

    r = await client.post(
        "/api/v1/tenants",
        headers={"Authorization": f"Bearer {_encode_token(uid)}"},
        json={
            "name": "Rollback Test",
            "base_currency": "SGD",
            "financial_year_start_month": 1,
            "financial_year_start_day": 1,
        },
    )
    assert r.status_code == 500

    async with session_factory() as s:
        assert (await s.execute(select(TenantModel))).scalars().all() == []
        assert (await s.execute(select(TenantUserModel))).scalars().all() == []
        assert (await s.execute(select(AccountModel))).scalars().all() == []
        assert (await s.execute(select(AuditLogModel))).scalars().all() == []


@pytest.mark.asyncio
async def test_coa_unique_per_tenant(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    from coa_service.modules.coa.infrastructure.models import AccountType
    from sqlalchemy.exc import IntegrityError

    tid = uuid.uuid4()
    uid = uuid.uuid4()
    now = datetime.now(UTC)
    async with session_factory() as s:
        await _create_user(s, user_id=uid, email="uq@example.com")
        s.add(
            TenantModel(
                id=tid,
                name="T",
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
        a1 = AccountModel(
            id=uuid.uuid4(),
            tenant_id=tid,
            code="1000",
            name="A",
            account_type=AccountType.ASSET,
            parent_id=None,
            is_active=True,
            is_system_default=True,
            created_at=now,
            updated_at=now,
        )
        a2 = AccountModel(
            id=uuid.uuid4(),
            tenant_id=tid,
            code="1000",
            name="B",
            account_type=AccountType.ASSET,
            parent_id=None,
            is_active=True,
            is_system_default=True,
            created_at=now,
            updated_at=now,
        )
        s.add_all([a1, a2])
        with pytest.raises(IntegrityError):
            await s.commit()


@pytest.mark.asyncio
async def test_same_coa_code_different_tenants_ok(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from coa_service.modules.coa.infrastructure.models import AccountType

    t1 = uuid.uuid4()
    t2 = uuid.uuid4()
    uid = uuid.uuid4()
    now = datetime.now(UTC)
    async with session_factory() as s:
        await _create_user(s, user_id=uid, email="multi@example.com")
        for tid in (t1, t2):
            s.add(
                TenantModel(
                    id=tid,
                    name="T",
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
            s.add(
                AccountModel(
                    id=uuid.uuid4(),
                    tenant_id=tid,
                    code="1000",
                    name="Cash",
                    account_type=AccountType.ASSET,
                    parent_id=None,
                    is_active=True,
                    is_system_default=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        await s.commit()
