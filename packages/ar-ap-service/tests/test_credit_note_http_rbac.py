"""US-10 API contract: JWT, tenant header and delegated RBAC on credit note routes."""

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
from ar_ap_service.deps import get_credit_note_service
from ar_ap_service.modules.ar_ap.domain.entities import (
    CreditNote,
    CreditNoteLine,
    CreditNoteStatus,
)

_SECRET = "ar-ap-us10-test-secret"

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
INVOICE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
CUSTOMER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
REVENUE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


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


def _credit_note_body() -> dict:
    return {
        "issue_date": date(2026, 6, 1).isoformat(),
        "reason": "Invoice correction",
        "lines": [
            {
                "account_id": str(REVENUE_ID),
                "quantity": "1",
                "unit_price": "100.00",
                "description": "Credit for consulting service",
                "gst_rate": "0.09",
            }
        ],
    }


class _StubCreditNoteService:
    async def issue_credit_note(self, tenant_id, invoice_id, command, issued_by) -> CreditNote:
        line = command.lines[0]
        return CreditNote(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            customer_id=CUSTOMER_ID,
            credit_note_number="CN-2026-0001",
            issue_date=command.issue_date,
            reason=command.reason,
            status=CreditNoteStatus.ISSUED,
            subtotal=Decimal("100.00"),
            gst_amount=Decimal("9.00"),
            total=Decimal("109.00"),
            journal_entry_id="je-credit-note-1",
            created_by=issued_by,
            lines=[
                CreditNoteLine(
                    account_id=line.account_id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    description=line.description,
                    gst_rate=line.gst_rate,
                    line_total=Decimal("100.00"),
                    gst_amount=Decimal("9.00"),
                )
            ],
        )

    async def list_invoice_credit_notes(self, tenant_id, invoice_id) -> list[CreditNote]:
        return []


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("JWT_SECRET", _SECRET)
    monkeypatch.setenv("TENANT_INTERNAL_API_TOKEN", "internal-shared")
    monkeypatch.setenv("TENANT_SERVICE_URL", "http://tenant.invalid")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")

    import ar_ap_service.deps as deps

    deps.get_settings.cache_clear()

    import ar_ap_service.main as main_mod

    main_mod.app.dependency_overrides[get_credit_note_service] = lambda: _StubCreditNoteService()
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://ar-ap-test") as ac:
        yield ac
    main_mod.app.dependency_overrides.clear()
    deps.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_issue_credit_note_requires_bearer(client: AsyncClient) -> None:
    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/credit-notes",
        json=_credit_note_body(),
        headers={"X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_issue_credit_note_requires_tenant_header(client: AsyncClient) -> None:
    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/credit-notes",
        json=_credit_note_body(),
        headers=_bearer(uuid.uuid4()),
    )
    assert r.status_code == 422


# 11 — Viewer (lacking accounting:post) cannot issue a credit note
@pytest.mark.asyncio
async def test_viewer_forbidden_to_issue_credit_note(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ar_ap_service.deps as deps

    async def deny(**_: object) -> None:
        raise ForbiddenError("Viewers cannot issue credit notes.")

    monkeypatch.setattr(deps, "authorize_via_tenant_service", deny)

    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/credit-notes",
        json=_credit_note_body(),
        headers={**_bearer(uuid.uuid4()), "X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 403


# 9 — Owner/Accountant (with accounting:post) can issue a credit note
@pytest.mark.asyncio
async def test_authorized_user_can_issue_credit_note(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ar_ap_service.deps as deps

    async def allow(**_: object) -> None:
        return None

    monkeypatch.setattr(deps, "authorize_via_tenant_service", allow)

    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/credit-notes",
        json=_credit_note_body(),
        headers={**_bearer(uuid.uuid4()), "X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["credit_note_number"] == "CN-2026-0001"
    assert body["total"] == "109.00"
    assert body["gst_amount"] == "9.00"
    assert body["journal_entry_id"] == "je-credit-note-1"
    assert body["invoice_id"] == str(INVOICE_ID)
