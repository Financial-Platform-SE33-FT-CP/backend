"""US-8 API contract: JWT, tenant header and delegated RBAC on invoice routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

from accounting_shared.exceptions import ForbiddenError
from ar_ap_service.deps import get_invoice_service
from ar_ap_service.modules.ar_ap.domain.entities import Invoice, InvoiceLine, InvoiceStatus

_SECRET = "ar-ap-us8-test-secret"

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
CUSTOMER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
REVENUE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
GST_OUTPUT_CODE_ID = uuid.UUID("88888888-8888-8888-8888-888888888881")


def _bearer(uid: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uid),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }
    token = jwt.encode(payload, _SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _create_body() -> dict:
    return {
        "customer_id": str(CUSTOMER_ID),
        "issue_date": date(2026, 3, 1).isoformat(),
        "due_date": date(2026, 3, 31).isoformat(),
        "lines": [
            {
                "account_id": str(REVENUE_ID),
                "quantity": "10",
                "unit_price": "100",
                "gst_code_id": str(GST_OUTPUT_CODE_ID),
                "gst_rate": "0.09",
            }
        ],
    }


class _StubService:
    async def create_draft(self, tenant_id, command, created_by) -> Invoice:
        lines: list[InvoiceLine] = []

        for raw in command.lines:
            line = InvoiceLine(
                account_id=raw.account_id,
                quantity=raw.quantity,
                unit_price=raw.unit_price,
                description=raw.description,
                gst_code_id=raw.gst_code_id,
                gst_rate=raw.gst_rate,
            )
            line.recalculate()
            lines.append(line)

        return Invoice(
            tenant_id=tenant_id,
            customer_id=command.customer_id,
            issue_date=command.issue_date,
            due_date=command.due_date,
            status=InvoiceStatus.DRAFT,
            subtotal=Decimal("1000.00"),
            gst_amount=Decimal("90.00"),
            total=Decimal("1090.00"),
            created_by=created_by,
            lines=lines,
        )

    async def build_invoice_pdf(self, tenant_id, invoice_id) -> tuple[bytes, str]:
        return b"%PDF-1.4 test", "INV-2026-0001.pdf"


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", "internal-shared")
    monkeypatch.setenv("TENANT_SERVICE_URL", "http://tenant.invalid")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")

    import ar_ap_service.deps as deps

    deps.get_settings.cache_clear()

    import ar_ap_service.main as main_mod

    main_mod.app.dependency_overrides[get_invoice_service] = lambda: _StubService()
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://ar-ap-test") as ac:
        yield ac
    main_mod.app.dependency_overrides.clear()
    deps.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_requires_bearer(client: AsyncClient) -> None:
    r = await client.post(
        "/ar-ap/invoices", json=_create_body(), headers={"X-Tenant-ID": str(TENANT_ID)}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_requires_tenant_header(client: AsyncClient) -> None:
    r = await client.post("/ar-ap/invoices", json=_create_body(), headers=_bearer(uuid.uuid4()))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_viewer_forbidden_to_create(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ar_ap_service.deps as deps

    async def deny(**_: object) -> None:
        raise ForbiddenError("Viewers cannot create invoices.")

    monkeypatch.setattr(deps, "authorize_via_tenant_service", deny)

    r = await client.post(
        "/ar-ap/invoices",
        json=_create_body(),
        headers={**_bearer(uuid.uuid4()), "X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_authorized_user_can_create(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ar_ap_service.deps as deps

    async def allow(**_: object) -> None:
        return None

    monkeypatch.setattr(deps, "authorize_via_tenant_service", allow)

    r = await client.post(
        "/ar-ap/invoices",
        json=_create_body(),
        headers={**_bearer(uuid.uuid4()), "X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["total"] == "1090.00"
    assert body["lines"][0]["gst_code_id"] == str(GST_OUTPUT_CODE_ID)


@pytest.mark.asyncio
async def test_authorized_user_can_download_pdf(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ar_ap_service.deps as deps

    async def allow(**_: object) -> None:
        return None

    monkeypatch.setattr(deps, "authorize_via_tenant_service", allow)

    invoice_id = uuid.uuid4()
    r = await client.get(
        f"/ar-ap/invoices/{invoice_id}/pdf",
        headers={**_bearer(uuid.uuid4()), "X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
