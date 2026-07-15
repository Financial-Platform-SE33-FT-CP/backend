"""US-15/US-16 GST HTTP API and RBAC tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

from ar_ap_service.deps import get_gst_service
from ar_ap_service.modules.ar_ap.domain.entities import (
    GstCode,
    GstKind,
    GstSummary,
)

from .conftest import (
    GST_OUTPUT_CODE_ID,
    TENANT_A,
)

_SECRET = "ar-ap-gst-test-secret"
_USER_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


def _bearer(user_id: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)

    payload = {
        "sub": str(user_id),
        "email": "gst-user@test.local",
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }

    token = jwt.encode(
        payload,
        _SECRET,
        algorithm="HS256",
    )

    return {
        "Authorization": f"Bearer {token}",
    }


@pytest_asyncio.fixture
async def gst_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[tuple[AsyncClient, AsyncMock], None]:
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    monkeypatch.setenv(
        "TENANT_INTERNAL_API_TOKEN",
        "internal-test-token",
    )
    monkeypatch.setenv(
        "TENANT_SERVICE_URL",
        "http://tenant.invalid",
    )

    import ar_ap_service.deps as deps

    async def allow_all(
        *_: object,
        **__: object,
    ) -> None:
        return None

    monkeypatch.setattr(
        deps,
        "authorize_via_tenant_service",
        allow_all,
    )

    deps.get_settings.cache_clear()

    from ar_ap_service.main import create_app

    app = create_app()

    service = AsyncMock()

    service.list_codes = AsyncMock(
        return_value=[
            GstCode(
                id=GST_OUTPUT_CODE_ID,
                tenant_id=TENANT_A,
                code="SR-OUTPUT",
                rate=Decimal("0.09"),
                gst_kind=GstKind.OUTPUT,
                is_active=True,
            )
        ]
    )

    service.ensure_default_codes = AsyncMock(
    return_value=[
        GstCode(
            id=GST_OUTPUT_CODE_ID,
            tenant_id=TENANT_A,
            code="SR-OUTPUT",
            rate=Decimal("0.09"),
            gst_kind=GstKind.OUTPUT,
            is_active=True,
            )
        ]
    )

    service.get_summary = AsyncMock(
        return_value=GstSummary(
            reporting_period="2026-Q2",
            output_tax=Decimal("81.00"),
            input_tax=Decimal("45.00"),
            zero_rated_supplies=Decimal("200.00"),
            exempt_supplies=Decimal("300.00"),
        )
    )

    service.build_summary_csv = AsyncMock(
        return_value=(
            (
                b"reporting_period,output_tax,input_tax,"
                b"net_gst_payable,zero_rated_supplies,"
                b"exempt_supplies\n"
                b"2026-Q2,81.00,45.00,36.00,200.00,300.00\n"
            ),
            "gst-summary-2026-Q2.csv",
        )
    )

    async def override_gst_service() -> AsyncMock:
        return service

    app.dependency_overrides[get_gst_service] = (
        override_gst_service
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://ar-ap-test",
    ) as client:
        yield client, service

    app.dependency_overrides.clear()
    deps.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gst_summary_requires_bearer_token(
    gst_http_client: tuple[AsyncClient, AsyncMock],
) -> None:
    client, _ = gst_http_client

    response = await client.get(
        "/ar-ap/gst/summary",
        params={"reporting_period": "2026-Q2"},
        headers={
            "X-Tenant-ID": str(TENANT_A),
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_gst_codes(
    gst_http_client: tuple[AsyncClient, AsyncMock],
) -> None:
    client, service = gst_http_client

    response = await client.get(
        "/ar-ap/gst/codes",
        headers={
            **_bearer(_USER_ID),
            "X-Tenant-ID": str(TENANT_A),
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body == [
        {
            "id": str(GST_OUTPUT_CODE_ID),
            "tenant_id": str(TENANT_A),
            "code": "SR-OUTPUT",
            "rate": "0.09",
            "gst_kind": "output",
            "is_active": True,
        }
    ]

    service.list_codes.assert_awaited_once_with(
        TENANT_A,
        active_only=True,
    )


@pytest.mark.asyncio
async def test_initialize_default_gst_codes(
    gst_http_client: tuple[AsyncClient, AsyncMock],
) -> None:
    client, service = gst_http_client

    response = await client.post(
        "/ar-ap/gst/codes/defaults",
        headers={
            **_bearer(_USER_ID),
            "X-Tenant-ID": str(TENANT_A),
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body == [
        {
            "id": str(GST_OUTPUT_CODE_ID),
            "tenant_id": str(TENANT_A),
            "code": "SR-OUTPUT",
            "rate": "0.09",
            "gst_kind": "output",
            "is_active": True,
        }
    ]

    service.ensure_default_codes.assert_awaited_once_with(
        TENANT_A,
    )


@pytest.mark.asyncio
async def test_get_gst_summary(
    gst_http_client: tuple[AsyncClient, AsyncMock],
) -> None:
    client, service = gst_http_client

    response = await client.get(
        "/ar-ap/gst/summary",
        params={"reporting_period": "2026-Q2"},
        headers={
            **_bearer(_USER_ID),
            "X-Tenant-ID": str(TENANT_A),
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body == {
        "reporting_period": "2026-Q2",
        "output_tax": "81.00",
        "input_tax": "45.00",
        "net_gst_payable": "36.00",
        "zero_rated_supplies": "200.00",
        "exempt_supplies": "300.00",
    }

    service.get_summary.assert_awaited_once_with(
        TENANT_A,
        "2026-Q2",
    )


@pytest.mark.asyncio
async def test_export_gst_summary_csv(
    gst_http_client: tuple[AsyncClient, AsyncMock],
) -> None:
    client, service = gst_http_client

    response = await client.get(
        "/ar-ap/gst/export",
        params={"reporting_period": "2026-Q2"},
        headers={
            **_bearer(_USER_ID),
            "X-Tenant-ID": str(TENANT_A),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "text/csv"
    )
    assert response.headers["content-disposition"] == (
        'attachment; filename="gst-summary-2026-Q2.csv"'
    )
    assert b"2026-Q2,81.00,45.00,36.00" in response.content

    service.build_summary_csv.assert_awaited_once_with(
        TENANT_A,
        "2026-Q2",
    )
