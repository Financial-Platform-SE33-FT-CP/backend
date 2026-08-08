"""HTTP integration tests for billing endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from accounting_shared.exceptions import ForbiddenError
from billing_service import deps
from billing_service.config import BillingSettings
from billing_service.modules.billing.interfaces.api import router as billing_router
from tenant_service.modules.tenants.infrastructure.models import TenantModel

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _headers(auth_headers: dict[str, str], tenant_id: uuid.UUID = TENANT_ID) -> dict[str, str]:
    return {**auth_headers, "X-Tenant-ID": str(tenant_id)}


async def _seed_usage(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    *,
    invoice_dates: list[datetime] | None = None,
    user_statuses: list[str] | None = None,
) -> None:
    invoice_dates = invoice_dates or []
    user_statuses = user_statuses or []
    async with session_factory() as session:
        for index, created_at in enumerate(invoice_dates):
            await session.execute(
                text(
                    "INSERT INTO invoices (id, tenant_id, created_at) "
                    "VALUES (:id, :tenant_id, :created_at)"
                ),
                {
                    "id": f"invoice-{index}",
                    "tenant_id": str(tenant_id),
                    "created_at": created_at.isoformat(),
                },
            )
        for index, status in enumerate(user_statuses):
            await session.execute(
                text(
                    "INSERT INTO tenant_users (id, tenant_id, status) "
                    "VALUES (:id, :tenant_id, :status)"
                ),
                {"id": f"user-{index}", "tenant_id": str(tenant_id), "status": status},
            )
        await session.commit()


async def _load_tenant(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID = TENANT_ID,
) -> TenantModel:
    async with session_factory() as session:
        tenant = await session.get(TenantModel, tenant_id)
        assert tenant is not None
        return tenant


@pytest.mark.asyncio
async def test_health_endpoints(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/billing/health-complete")).json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_get_plan_returns_usage_and_limits(
    client: AsyncClient,
    auth_headers: dict[str, str],
    billing_settings: BillingSettings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
) -> None:
    tenant = tenant_factory(plan_tier="growth", subscription_status="active")
    await persist_tenant(tenant)
    now = datetime.now(UTC)
    await _seed_usage(
        session_factory,
        TENANT_ID,
        invoice_dates=[now, now - timedelta(days=40)],
        user_statuses=["active", "active", "inactive"],
    )

    response = await client.get("/billing/plan", headers=_headers(auth_headers))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "plan_tier": "growth",
        "subscription_status": "active",
        "trial_ends_at": None,
        "subscription_ends_at": None,
        "usage": {
            "invoices_this_month": 1,
            "max_invoices": 500,
            "users": 2,
            "max_users": 10,
        },
    }
    assert billing_settings.stripe_mock_mode is True


@pytest.mark.asyncio
async def test_get_plan_expires_trial_and_persists_downgrade(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
) -> None:
    tenant = tenant_factory(
        plan_tier="pro",
        subscription_status="trial",
        trial_ends_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await persist_tenant(tenant)

    response = await client.get("/billing/plan", headers=_headers(auth_headers))

    assert response.status_code == 200, response.text
    assert response.json()["plan_tier"] == "starter"
    assert response.json()["subscription_status"] == "expired"
    stored = await _load_tenant(session_factory)
    assert stored.plan_tier == "starter"
    assert stored.subscription_status == "expired"


@pytest.mark.asyncio
async def test_get_plan_rejects_missing_authentication(
    client: AsyncClient,
) -> None:
    response = await client.get("/billing/plan", headers={"X-Tenant-ID": str(TENANT_ID)})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_plan_requires_tenant_header(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get("/billing/plan", headers=auth_headers)

    assert response.status_code == 422
    assert "X-Tenant-ID header is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_plan_returns_not_found_for_unknown_tenant(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get("/billing/plan", headers=_headers(auth_headers))

    assert response.status_code == 404
    assert response.json()["detail"] == "Tenant not found."


@pytest.mark.asyncio
async def test_get_plan_honors_delegated_forbidden_response(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def deny(**_: object) -> None:
        raise ForbiddenError("You do not have permission for this action.")

    monkeypatch.setattr(deps, "authorize_via_tenant_service", deny)

    response = await client.get("/billing/plan", headers=_headers(auth_headers))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_change_plan_mock_mode_creates_checkout_url(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(tenant_factory(subscription_status="active"))

    response = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers),
        json={"plan_tier": "growth"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is False
    assert body["url"].startswith("http://frontend.test/billing?mock_session=")
    assert (await _load_tenant(session_factory)).plan_tier == "starter"


@pytest.mark.asyncio
async def test_change_plan_mock_mode_updates_existing_subscription(
    client: AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(
        tenant_factory(
            plan_tier="starter",
            subscription_status="active",
            stripe_subscription_id="sub_existing",
        )
    )

    response = await client.post(
        "/billing/create-checkout-session",
        headers=_headers(auth_headers),
        json={"plan_tier": "pro"},
    )

    assert response.status_code == 200
    assert response.json()["changed"] is True
    assert response.json()["url"] == "http://frontend.test/billing?updated=true"
    assert (await _load_tenant(session_factory)).plan_tier == "pro"


@pytest.mark.asyncio
async def test_change_plan_rejects_invalid_plan_and_body(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(tenant_factory(subscription_status="active"))

    invalid_plan = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers),
        json={"plan_tier": "enterprise"},
    )
    invalid_body = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers),
        json=["growth"],
    )
    invalid_json = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers),
        content=b"{",
    )

    assert invalid_plan.status_code == 400
    assert invalid_body.status_code == 400
    assert invalid_json.status_code == 400


@pytest.mark.asyncio
async def test_change_plan_maps_stripe_creation_errors_to_bad_gateway(
    client: AsyncClient,
    auth_headers: dict[str, str],
    billing_settings: BillingSettings,
    tenant_factory,
    persist_tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    billing_settings.stripe_mock_mode = False
    billing_settings.stripe_secret_key = "sk_test_key"
    await persist_tenant(tenant_factory(subscription_status="active"))
    stripe_error = billing_router.stripe_lib.error.StripeError("stripe unavailable")
    monkeypatch.setattr(
        billing_router.stripe_lib.Customer,
        "create",
        MagicMock(side_effect=stripe_error),
    )

    customer_error = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers),
        json={"plan_tier": "growth"},
    )

    assert customer_error.status_code == 502
    assert customer_error.json()["detail"] == "Unable to create Stripe customer."

    await persist_tenant(
        tenant_factory(
            tenant_id=OTHER_TENANT_ID,
            subscription_status="active",
            stripe_customer_id="cus_existing",
        )
    )
    monkeypatch.setattr(
        billing_router.stripe_lib.checkout.Session,
        "create",
        MagicMock(side_effect=stripe_error),
    )
    checkout_error = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers, OTHER_TENANT_ID),
        json={"plan_tier": "growth"},
    )

    assert checkout_error.status_code == 502
    assert checkout_error.json()["detail"] == "Unable to create Stripe checkout session."


@pytest.mark.asyncio
async def test_change_plan_uses_stripe_checkout_when_configured(
    client: AsyncClient,
    auth_headers: dict[str, str],
    billing_settings: BillingSettings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    billing_settings.stripe_mock_mode = False
    billing_settings.stripe_secret_key = "sk_test_key"
    await persist_tenant(tenant_factory(subscription_status="active"))

    customer = SimpleNamespace(id="cus_new")
    checkout_session = SimpleNamespace(url="https://checkout.test/session")
    customer_create = MagicMock(return_value=customer)
    checkout_create = MagicMock(return_value=checkout_session)
    monkeypatch.setattr(billing_router.stripe_lib.Customer, "create", customer_create)
    monkeypatch.setattr(billing_router.stripe_lib.checkout.Session, "create", checkout_create)

    response = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers),
        json={"plan_tier": "growth"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://checkout.test/session", "changed": False}
    assert (await _load_tenant(session_factory)).stripe_customer_id == "cus_new"
    customer_create.assert_called_once_with(metadata={"tenant_id": str(TENANT_ID)})
    checkout_create.assert_called_once()
    assert checkout_create.call_args.kwargs["line_items"] == [
        {"price": "price_growth", "quantity": 1}
    ]


@pytest.mark.asyncio
async def test_change_plan_updates_active_stripe_subscription(
    client: AsyncClient,
    auth_headers: dict[str, str],
    billing_settings: BillingSettings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    billing_settings.stripe_mock_mode = False
    billing_settings.stripe_secret_key = "sk_test_key"
    await persist_tenant(
        tenant_factory(
            plan_tier="starter",
            subscription_status="active",
            stripe_subscription_id="sub_existing",
        )
    )
    retrieve = MagicMock(
        return_value={"status": "active", "items": {"data": [{"id": "si_existing"}]}}
    )
    modify = MagicMock(return_value={"status": "active"})
    monkeypatch.setattr(billing_router.stripe_lib.Subscription, "retrieve", retrieve)
    monkeypatch.setattr(billing_router.stripe_lib.Subscription, "modify", modify)

    response = await client.post(
        "/billing/change-plan",
        headers=_headers(auth_headers),
        json={"plan_tier": "growth"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    modify.assert_called_once_with(
        "sub_existing",
        items=[{"id": "si_existing", "price": "price_growth"}],
        proration_behavior="create_prorations",
        metadata={"tenant_id": str(TENANT_ID), "plan_tier": "growth"},
    )
    assert (await _load_tenant(session_factory)).plan_tier == "growth"


@pytest.mark.asyncio
async def test_mock_webhook_updates_checkout_subscription(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(tenant_factory(subscription_status="trial"))

    response = await client.post(
        "/billing/webhook",
        json={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"tenant_id": str(TENANT_ID), "plan_tier": "pro"},
                    "customer": "cus_123",
                    "subscription": "sub_123",
                }
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    tenant = await _load_tenant(session_factory)
    assert tenant.plan_tier == "pro"
    assert tenant.subscription_status == "active"
    assert tenant.stripe_customer_id == "cus_123"
    assert tenant.stripe_subscription_id == "sub_123"
    assert tenant.trial_ends_at is None


@pytest.mark.asyncio
async def test_mock_webhook_maps_subscription_and_payment_statuses(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(
        tenant_factory(
            plan_tier="growth",
            subscription_status="active",
            stripe_subscription_id="sub_123",
        )
    )

    updated = await client.post(
        "/billing/webhook",
        json={
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "object": "subscription",
                    "id": "sub_123",
                    "status": "past_due",
                    "metadata": {"plan_tier": "pro"},
                }
            },
        },
    )
    failed = await client.post(
        "/billing/webhook",
        json={
            "type": "invoice.payment_failed",
            "data": {"object": {"subscription": "sub_123"}},
        },
    )
    succeeded = await client.post(
        "/billing/webhook",
        json={
            "type": "invoice.payment_succeeded",
            "data": {"object": {"subscription": "sub_123"}},
        },
    )
    deleted = await client.post(
        "/billing/webhook",
        json={
            "type": "customer.subscription.deleted",
            "data": {"object": {"object": "subscription", "id": "sub_123", "status": "canceled"}},
        },
    )

    assert all(response.status_code == 200 for response in (updated, failed, succeeded, deleted))
    tenant = await _load_tenant(session_factory)
    assert tenant.plan_tier == "pro"
    assert tenant.subscription_status == "canceled"


@pytest.mark.asyncio
async def test_mock_webhook_ignores_invalid_json_and_unknown_tenant(
    client: AsyncClient,
) -> None:
    invalid = await client.post("/billing/webhook", content=b"not-json")
    unknown = await client.post(
        "/billing/webhook",
        json={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {
                        "tenant_id": "00000000-0000-0000-0000-000000000099",
                        "plan_tier": "growth",
                    }
                }
            },
        },
    )

    assert invalid.status_code == 200
    assert invalid.json() == {"status": "ignored"}
    assert unknown.status_code == 200
    assert unknown.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_signed_webhook_requires_configuration_and_valid_signature(
    client: AsyncClient,
    billing_settings: BillingSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    billing_settings.stripe_mock_mode = False
    not_configured = await client.post("/billing/webhook", content=b"{}")
    assert not_configured.status_code == 503

    billing_settings.stripe_secret_key = "sk_test_key"
    billing_settings.stripe_webhook_secret = "whsec_test"
    monkeypatch.setattr(
        billing_router.stripe_lib.Webhook,
        "construct_event",
        MagicMock(side_effect=ValueError("invalid signature")),
    )
    invalid_signature = await client.post(
        "/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "bad"},
    )

    assert invalid_signature.status_code == 401


@pytest.mark.asyncio
async def test_signed_webhook_processes_constructed_event(
    client: AsyncClient,
    billing_settings: BillingSettings,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    persist_tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    billing_settings.stripe_mock_mode = False
    billing_settings.stripe_secret_key = "sk_test_key"
    billing_settings.stripe_webhook_secret = "whsec_test"
    await persist_tenant(
        tenant_factory(
            subscription_status="active",
            stripe_subscription_id="sub_123",
        )
    )
    event = SimpleNamespace(
        type="invoice.payment_failed",
        data=SimpleNamespace(object={"subscription": "sub_123"}),
    )
    construct_event = MagicMock(return_value=event)
    monkeypatch.setattr(billing_router.stripe_lib.Webhook, "construct_event", construct_event)

    response = await client.post(
        "/billing/webhook",
        content=b"{}",
        headers={"stripe-signature": "sig_test"},
    )

    assert response.status_code == 200
    construct_event.assert_called_once_with(b"{}", "sig_test", "whsec_test")
    assert (await _load_tenant(session_factory)).subscription_status == "past_due"


@pytest.mark.asyncio
async def test_plan_limit_enforces_starter_boundary_and_pro_unlimited(
    client: AsyncClient,
    billing_settings: BillingSettings,
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(tenant_factory(plan_tier="starter", subscription_status="active"))
    headers = {
        "X-Internal-Token": billing_settings.tenant_internal_api_token,
        "X-Tenant-ID": str(TENANT_ID),
    }

    below_limit = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "users", "current_count": "2"},
        headers=headers,
    )
    at_limit = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "users", "current_count": "3"},
        headers=headers,
    )

    assert below_limit.json() == {"allowed": True, "limit": 3, "current": 2}
    assert at_limit.json() == {"allowed": False, "limit": 3, "current": 3}

    await persist_tenant(
        tenant_factory(
            tenant_id=OTHER_TENANT_ID,
            plan_tier="pro",
            subscription_status="active",
        )
    )
    unlimited = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "invoices", "current_count": "999999"},
        headers={**headers, "X-Tenant-ID": str(OTHER_TENANT_ID)},
    )
    assert unlimited.json() == {"allowed": True, "limit": None, "current": 999999}


@pytest.mark.asyncio
async def test_plan_limit_expires_trial_and_allows_unknown_resource(
    client: AsyncClient,
    billing_settings: BillingSettings,
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(
        tenant_factory(
            plan_tier="growth",
            subscription_status="trial",
            trial_ends_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    headers = {
        "X-Internal-Token": billing_settings.tenant_internal_api_token,
        "X-Tenant-ID": str(TENANT_ID),
    }

    expired = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "invoices", "current_count": "100"},
        headers=headers,
    )
    unknown = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "reports", "current_count": "100000"},
        headers=headers,
    )

    assert expired.json() == {"allowed": False, "limit": 100, "current": 100}
    assert unknown.json() == {"allowed": True, "limit": None, "current": 100000}


@pytest.mark.asyncio
async def test_plan_limit_rejects_bad_internal_headers_and_values(
    client: AsyncClient,
    billing_settings: BillingSettings,
    tenant_factory,
    persist_tenant,
) -> None:
    await persist_tenant(tenant_factory(subscription_status="active"))
    valid_headers = {
        "X-Internal-Token": billing_settings.tenant_internal_api_token,
        "X-Tenant-ID": str(TENANT_ID),
    }

    bad_token = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "users", "current_count": "0"},
        headers={**valid_headers, "X-Internal-Token": "wrong"},
    )
    bad_count = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "users", "current_count": "not-an-int"},
        headers=valid_headers,
    )
    bad_tenant = await client.get(
        "/billing/internal/check-plan-limit",
        params={"resource": "users", "current_count": "0"},
        headers={**valid_headers, "X-Tenant-ID": "not-a-uuid"},
    )

    assert bad_token.status_code == 401
    assert bad_count.status_code == 400
    assert bad_tenant.status_code == 400
