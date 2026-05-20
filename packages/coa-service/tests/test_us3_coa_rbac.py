"""US-3: Chart-of-accounts HTTP API requires JWT, tenant header, and delegated RBAC."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from accounting_shared.exceptions import ForbiddenError, ServiceUnavailableError
from accounting_shared.types import TenantId, UserId
from httpx import ASGITransport, AsyncClient, Response
from jose import jwt

from coa_service.config import COASettings
from coa_service.deps import authorize_via_tenant_service, get_coa_service, get_settings

_SECRET = "coa-us3-test-secret"


def _bearer(uid: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uid),
        "email": "u@test.local",
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }
    token = jwt.encode(payload, _SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def coa_async_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", "internal-shared")
    monkeypatch.setenv("TENANT_SERVICE_URL", "http://tenant.invalid")

    import coa_service.deps as deps

    async def allow_all(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(deps, "authorize_via_tenant_service", allow_all)

    deps.get_settings.cache_clear()
    deps._engine = None  # noqa: SLF001
    deps._session_factory = None  # noqa: SLF001

    from coa_service.main import create_app

    app = create_app()
    svc = AsyncMock()
    svc.list_accounts = AsyncMock(return_value=[])

    async def _svc_override() -> object:
        return svc

    app.dependency_overrides[get_coa_service] = _svc_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://coa-test") as ac:
        yield ac
    app.dependency_overrides.clear()
    deps.get_settings.cache_clear()
    deps._engine = None  # noqa: SLF001
    deps._session_factory = None  # noqa: SLF001


@pytest.mark.asyncio
async def test_list_accounts_requires_bearer_header(coa_async_client: AsyncClient) -> None:
    tid = uuid.uuid4()
    r = await coa_async_client.get("/coa/accounts", headers={"X-Tenant-ID": str(tid)})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_accounts_requires_tenant_header(coa_async_client: AsyncClient) -> None:
    uid = uuid.uuid4()
    r = await coa_async_client.get("/coa/accounts", headers=_bearer(uid))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_accounts_ok_with_headers(coa_async_client: AsyncClient) -> None:
    uid = uuid.uuid4()
    tid = uuid.uuid4()
    r = await coa_async_client.get(
        "/coa/accounts", headers={**_bearer(uid), "X-Tenant-ID": str(tid)}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_list_accounts_forbidden_when_delegate_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", "internal-shared")
    monkeypatch.setenv("TENANT_SERVICE_URL", "http://tenant.invalid")

    import coa_service.deps as deps

    async def deny(*_: object, **__: object) -> None:
        raise ForbiddenError("Denied.")

    monkeypatch.setattr(deps, "authorize_via_tenant_service", deny)
    deps.get_settings.cache_clear()

    svc = AsyncMock()
    svc.list_accounts = AsyncMock(return_value=[])

    async def _svc_override() -> object:
        return svc

    from coa_service.main import create_app

    app = create_app()
    app.dependency_overrides[get_coa_service] = _svc_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://coa-test") as ac:
        uid = uuid.uuid4()
        tid = uuid.uuid4()
        r = await ac.get("/coa/accounts", headers={**_bearer(uid), "X-Tenant-ID": str(tid)})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_authorize_not_member_via_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAC:
        async def __aenter__(self) -> FakeAC:
            return self

        async def __aexit__(self, *_x: object, **_y: object) -> None:
            return None

        async def post(self, *_a: object, **_k: object) -> Response:
            return Response(
                status_code=200,
                json={"allowed": False, "reason": "not_member"},
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_k: FakeAC())

    get_settings.cache_clear()

    uid = uuid.uuid4()
    tid = uuid.uuid4()

    settings = COASettings(
        jwt_secret=_SECRET,
        tenant_internal_api_token="tok",
        tenant_service_url="http://tenant.invalid",
        database_url="sqlite+aiosqlite://",
        debug=False,
    )

    with pytest.raises(ForbiddenError, match="Not a member of this tenant."):
        await authorize_via_tenant_service(
            settings=settings,
            user_id=UserId(uid),
            tenant_id=TenantId(tid),
            permission="coa:read",
        )


@pytest.mark.asyncio
async def test_authorize_missing_internal_token_raises() -> None:
    settings = COASettings(
        tenant_internal_api_token="",
        tenant_service_url="http://tenant.invalid",
        database_url="sqlite+aiosqlite://",
        debug=False,
        jwt_secret="x",
    )
    uid = uuid.uuid4()
    tid = uuid.uuid4()

    with pytest.raises(ServiceUnavailableError):
        await authorize_via_tenant_service(
            settings=settings,
            user_id=UserId(uid),
            tenant_id=TenantId(tid),
            permission="coa:read",
        )
