"""Unit tests for billing router normalization and webhook lookup helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from billing_service.modules.billing.interfaces.api import router as billing_router


def _result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def test_stored_plan_tier_falls_back_to_starter() -> None:
    assert billing_router._stored_plan_tier("growth").value == "growth"
    assert billing_router._stored_plan_tier("unknown").value == "starter"
    assert billing_router._stored_plan_tier(None).value == "starter"


def test_requested_plan_tier_rejects_unknown_value() -> None:
    with pytest.raises(billing_router.HTTPException, match="Invalid plan tier"):
        billing_router._requested_plan_tier("enterprise")


def test_event_helpers_support_mappings_and_attributes() -> None:
    mapping_event = {"status": "active", "metadata": {"plan_tier": "pro"}}
    object_event = SimpleNamespace(status="trialing", metadata=None)

    assert billing_router._event_string(mapping_event, "status") == "active"
    assert billing_router._event_string(object_event, "status") == "trialing"
    assert billing_router._event_string(mapping_event, "missing") is None
    assert billing_router._event_metadata(mapping_event) == {"plan_tier": "pro"}
    assert billing_router._event_metadata(object_event) == {}


def test_event_value_supports_getter_objects() -> None:
    class GetterEvent:
        def get(self, key: str) -> object:
            return {"status": "active"}.get(key)

    assert billing_router._event_string(GetterEvent(), "status") == "active"


def test_event_metadata_supports_to_dict() -> None:
    metadata = SimpleNamespace(to_dict=lambda: {"tenant_id": "tenant"})
    event = SimpleNamespace(metadata=metadata)

    assert billing_router._event_metadata(event) == {"tenant_id": "tenant"}


@pytest.mark.asyncio
async def test_find_tenant_prefers_metadata_tenant_id() -> None:
    tenant = object()
    session = AsyncMock()
    session.execute.return_value = _result(tenant)

    result = await billing_router._find_tenant_for_event(
        session,
        {"metadata": {"tenant_id": "00000000-0000-0000-0000-000000000001"}},
    )

    assert result is tenant
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_tenant_falls_back_to_subscription_then_customer() -> None:
    subscription_tenant = object()
    customer_tenant = object()
    session = AsyncMock()
    session.execute.side_effect = [_result(subscription_tenant)]

    result = await billing_router._find_tenant_for_event(
        session,
        {"client_reference_id": "not-a-uuid", "subscription": "sub_123"},
    )

    assert result is subscription_tenant
    assert session.execute.await_count == 1

    session.reset_mock()
    session.execute.side_effect = [_result(customer_tenant)]

    result = await billing_router._find_tenant_for_event(
        session,
        {"customer": "cus_123"},
    )

    assert result is customer_tenant
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_find_tenant_uses_subscription_object_id() -> None:
    tenant = object()
    session = AsyncMock()
    session.execute.return_value = _result(tenant)

    result = await billing_router._find_tenant_for_event(
        session,
        {"object": "subscription", "id": "sub_123"},
    )

    assert result is tenant


@pytest.mark.asyncio
async def test_find_tenant_returns_none_when_all_identifiers_miss() -> None:
    session = AsyncMock()
    result = await billing_router._find_tenant_for_event(session, {})

    assert result is None
    session.execute.assert_not_awaited()
