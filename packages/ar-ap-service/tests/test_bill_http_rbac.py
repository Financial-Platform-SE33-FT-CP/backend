"""US-11 API contract: GST code propagation on bill routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

from ar_ap_service.deps import get_bill_service
from ar_ap_service.modules.ar_ap.domain.entities import (
    Bill,
    BillLine,
    BillStatus,
)

_SECRET = "ar-ap-us11-test-secret"

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
VENDOR_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
EXPENSE_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
GST_INPUT_CODE_ID = uuid.UUID("88888888-8888-8888-8888-888888888882")


def _bearer(user_id: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)

    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
    }

    token = jwt.encode(payload, _SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _create_body() -> dict:
    return {
        "vendor_id": str(VENDOR_ID),
        "issue_date": date(2026, 4, 1).isoformat(),
        "due_date": date(2026, 4, 30).isoformat(),
        "lines": [
            {
                "account_id": str(EXPENSE_ID),
                "quantity": "1",
                "unit_price": "100.00",
                "description": "Office supplies",
                "gst_code_id": str(GST_INPUT_CODE_ID),
                "gst_rate": "0.09",
            }
        ],
    }


class _StubBillService:
    async def create_draft(
        self,
        tenant_id,
        vendor_id,
        *,
        issue_date,
        due_date,
        lines_input,
        created_by,
    ) -> Bill:
        lines: list[BillLine] = []

        for raw in lines_input:
            line = BillLine(
                account_id=raw["account_id"],
                quantity=raw["quantity"],
                unit_price=raw["unit_price"],
                description=raw.get("description"),
                gst_code_id=raw.get("gst_code_id"),
                gst_rate=raw["gst_rate"],
            )
            line.recalculate()
            lines.append(line)

        bill = Bill(
            tenant_id=tenant_id,
            vendor_id=vendor_id,
            bill_number="",
            issue_date=issue_date,
            due_date=due_date,
            status=BillStatus.DRAFT,
            created_by=created_by,
            lines=lines,
        )
        bill.recalculate_totals()
        return bill


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", "internal-shared")
    monkeypatch.setenv("TENANT_SERVICE_URL", "http://tenant.invalid")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")

    import ar_ap_service.deps as deps

    async def allow(**_: object) -> None:
        return None

    monkeypatch.setattr(
        deps,
        "authorize_via_tenant_service",
        allow,
    )
    deps.get_settings.cache_clear()

    import ar_ap_service.main as main_mod

    main_mod.app.dependency_overrides[get_bill_service] = lambda: _StubBillService()

    transport = ASGITransport(app=main_mod.app)

    async with AsyncClient(
        transport=transport,
        base_url="http://ar-ap-test",
    ) as async_client:
        yield async_client

    main_mod.app.dependency_overrides.clear()
    deps.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_authorized_user_can_create_bill_with_gst_code(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/ar-ap/bills",
        json=_create_body(),
        headers={
            **_bearer(uuid.uuid4()),
            "X-Tenant-ID": str(TENANT_ID),
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["status"] == "draft"
    assert body["subtotal"] == "100.00"
    assert body["gst_amount"] == "9.00"
    assert body["total"] == "109.00"
    assert body["lines"][0]["gst_code_id"] == str(GST_INPUT_CODE_ID)
