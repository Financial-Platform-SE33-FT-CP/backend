"""US-9 API contract: JWT, tenant header and delegated RBAC on payment routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

from accounting_shared.exceptions import ForbiddenError
from ar_ap_service.deps import get_payment_service
from ar_ap_service.modules.ar_ap.domain.entities import Payment, PaymentMethod

_SECRET = "ar-ap-us9-test-secret"

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
INVOICE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
CUSTOMER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
BANK_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


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


def _payment_body() -> dict:
    return {
        "payment_date": date(2026, 6, 1).isoformat(),
        "amount": "100.00",
        "payment_method": "bank_transfer",
        "reference": "BANK-REF-001",
        "deposit_account_id": str(BANK_ID),
    }


class _StubPaymentService:
    async def record_payment(self, tenant_id, invoice_id, command, recorded_by) -> Payment:
        return Payment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            customer_id=CUSTOMER_ID,
            amount=command.amount,
            payment_date=command.payment_date,
            payment_method=PaymentMethod(command.payment_method),
            reference=command.reference,
            deposit_account_id=command.deposit_account_id,
            journal_entry_id="je-payment-1",
            created_by=recorded_by,
        )

    async def list_invoice_payments(self, tenant_id, invoice_id) -> list[Payment]:
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

    main_mod.app.dependency_overrides[get_payment_service] = lambda: _StubPaymentService()
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://ar-ap-test") as ac:
        yield ac
    main_mod.app.dependency_overrides.clear()
    deps.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_record_payment_requires_bearer(client: AsyncClient) -> None:
    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/payments",
        json=_payment_body(),
        headers={"X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_record_payment_requires_tenant_header(client: AsyncClient) -> None:
    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/payments",
        json=_payment_body(),
        headers=_bearer(uuid.uuid4()),
    )
    assert r.status_code == 422


# 10 — Viewer (lacking accounting:post) cannot record a payment
@pytest.mark.asyncio
async def test_viewer_forbidden_to_record_payment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ar_ap_service.deps as deps

    async def deny(**_: object) -> None:
        raise ForbiddenError("Viewers cannot record payments.")

    monkeypatch.setattr(deps, "authorize_via_tenant_service", deny)

    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/payments",
        json=_payment_body(),
        headers={**_bearer(uuid.uuid4()), "X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 403


# 11 — Owner/Accountant (with accounting:post) can record a payment
@pytest.mark.asyncio
async def test_authorized_user_can_record_payment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ar_ap_service.deps as deps

    async def allow(**_: object) -> None:
        return None

    monkeypatch.setattr(deps, "authorize_via_tenant_service", allow)

    r = await client.post(
        f"/ar-ap/invoices/{INVOICE_ID}/payments",
        json=_payment_body(),
        headers={**_bearer(uuid.uuid4()), "X-Tenant-ID": str(TENANT_ID)},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["amount"] == "100.00"
    assert body["payment_method"] == "bank_transfer"
    assert body["journal_entry_id"] == "je-payment-1"
    assert body["invoice_id"] == str(INVOICE_ID)
