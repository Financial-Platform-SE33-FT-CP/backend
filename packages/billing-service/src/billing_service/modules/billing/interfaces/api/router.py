"""Billing service REST API — Stripe checkout, webhook, plan enforcement."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated

import stripe as stripe_lib
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.plans import PLAN_LIMITS, PlanTier
from accounting_shared.rbac import P_TENANT_READ, P_TENANT_UPDATE
from billing_service.config import BillingSettings
from billing_service.deps import (
    RequireBillingPermission,
    get_async_session,
    get_current_tenant_id_str,
    get_settings,
)
from tenant_service.modules.tenants.infrastructure.models import TenantModel

router = APIRouter(tags=["billing"])


def _stored_plan_tier(value: object) -> PlanTier:
    try:
        return PlanTier(str(value))
    except (TypeError, ValueError):
        return PlanTier.STARTER


def _requested_plan_tier(value: object) -> PlanTier:
    try:
        return PlanTier(str(value))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid plan tier: {value}") from e


def _event_value(event_obj: object, key: str) -> object:
    if isinstance(event_obj, Mapping):
        return event_obj.get(key)
    try:
        return event_obj[key]  # type: ignore[index]
    except (AttributeError, KeyError, TypeError):
        pass
    getter = getattr(event_obj, "get", None)
    if callable(getter):
        return getter(key)
    return getattr(event_obj, key, None)


def _event_metadata(event_obj: object) -> dict[str, object]:
    metadata = _event_value(event_obj, "metadata")
    if isinstance(metadata, Mapping):
        return dict(metadata)
    to_dict = getattr(metadata, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, dict):
            return converted
    return {}


def _event_string(event_obj: object, key: str) -> str | None:
    value = _event_value(event_obj, key)
    return value if isinstance(value, str) and value else None


async def _find_tenant_for_event(
    session: AsyncSession,
    event_obj: object,
) -> TenantModel | None:
    metadata = _event_metadata(event_obj)
    metadata_tenant_id = metadata.get("tenant_id")
    tenant_id = (
        metadata_tenant_id
        if isinstance(metadata_tenant_id, str)
        else _event_string(event_obj, "client_reference_id")
    )
    if tenant_id:
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            tenant_uuid = None
        if tenant_uuid is not None:
            result = await session.execute(select(TenantModel).where(TenantModel.id == tenant_uuid))
            tenant = result.scalar_one_or_none()
            if tenant is not None:
                return tenant

    subscription_id = _event_string(event_obj, "subscription")
    if subscription_id is None and _event_value(event_obj, "object") == "subscription":
        subscription_id = _event_string(event_obj, "id")
    if subscription_id:
        result = await session.execute(
            select(TenantModel).where(TenantModel.stripe_subscription_id == subscription_id)
        )
        tenant = result.scalar_one_or_none()
        if tenant is not None:
            return tenant

    customer_id = _event_string(event_obj, "customer")
    if customer_id:
        result = await session.execute(
            select(TenantModel).where(TenantModel.stripe_customer_id == customer_id)
        )
        return result.scalar_one_or_none()
    return None


@router.get("/health-complete")
async def health_complete() -> dict[str, str]:
    return {"status": "ok"}


# ── Plan Info (for frontend) ───────────────────────────────────────────


@router.get("/plan")
async def get_plan(
    tenant_id: Annotated[str, Depends(get_current_tenant_id_str)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[None, Depends(RequireBillingPermission(P_TENANT_READ))],
) -> dict:
    tenant_uuid = uuid.UUID(tenant_id)

    stmt = select(TenantModel).where(TenantModel.id == tenant_uuid)
    result = await session.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    # Count invoices this month for usage
    now = datetime.now(UTC)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    from sqlalchemy import text as sa_text

    invoice_count_result = await session.execute(
        sa_text("SELECT COUNT(*) FROM invoices WHERE tenant_id = :tid AND created_at >= :start"),
        {"tid": str(tenant_id), "start": start_of_month.isoformat()},
    )
    invoices_this_month = invoice_count_result.scalar() or 0

    # Count active tenant users
    user_count_result = await session.execute(
        sa_text("SELECT COUNT(*) FROM tenant_users WHERE tenant_id = :tid AND status = 'active'"),
        {"tid": str(tenant_id)},
    )
    user_count = user_count_result.scalar() or 0
    # Check trial expiry inline
    if (
        tenant.subscription_status == "trial"
        and tenant.trial_ends_at
        and tenant.trial_ends_at < now
    ):
        tenant.subscription_status = "expired"
        tenant.plan_tier = PlanTier.STARTER.value
        await session.flush()

    plan = _stored_plan_tier(tenant.plan_tier)
    limits = PLAN_LIMITS[plan]

    return {
        "plan_tier": tenant.plan_tier,
        "subscription_status": tenant.subscription_status,
        "trial_ends_at": tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None,
        "subscription_ends_at": (
            tenant.subscription_ends_at.isoformat() if tenant.subscription_ends_at else None
        ),
        "usage": {
            "invoices_this_month": invoices_this_month,
            "max_invoices": limits.get("max_monthly_invoices"),
            "users": user_count,
            "max_users": limits.get("max_users"),
        },
    }


# ── Stripe Checkout / Plan Changes ─────────────────────────────────────


@router.post("/change-plan")
@router.post("/create-checkout-session")
async def change_plan(
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant_id_str)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
    settings: Annotated[BillingSettings, Depends(get_settings)],
    _: Annotated[None, Depends(RequireBillingPermission(P_TENANT_UPDATE))],
) -> dict:
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be an object.")
    plan = _requested_plan_tier(body.get("plan_tier", PlanTier.GROWTH.value))
    plan_tier = plan.value

    tenant_uuid = uuid.UUID(tenant_id)

    stmt = select(TenantModel).where(TenantModel.id == tenant_uuid)
    result = await session.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    price_id = settings.stripe_price_ids.get(f"{plan.value}_monthly", "")
    if not price_id and not (settings.stripe_mock_mode or not settings.stripe_secret_key):
        raise HTTPException(status_code=500, detail="Price ID not configured.")

    updated_url = f"{settings.frontend_url}/billing?updated=true"

    # An existing Stripe subscription must be updated in place. Creating a new
    # checkout session here would leave the old subscription active as well.
    if tenant.stripe_subscription_id:
        if settings.stripe_mock_mode or not settings.stripe_secret_key:
            tenant.plan_tier = plan_tier
            await session.flush()
            return {"url": updated_url, "changed": True}

        stripe_lib.api_key = settings.stripe_secret_key
        try:
            subscription = stripe_lib.Subscription.retrieve(tenant.stripe_subscription_id)
        except stripe_lib.error.InvalidRequestError as e:
            if getattr(e, "http_status", None) != 404:
                raise HTTPException(
                    status_code=502,
                    detail="Unable to retrieve the existing Stripe subscription.",
                ) from e
            tenant.stripe_subscription_id = None
        except stripe_lib.error.StripeError as e:
            raise HTTPException(
                status_code=502,
                detail="Unable to retrieve the existing Stripe subscription.",
            ) from e
        else:
            subscription_status = _event_string(subscription, "status")
            if subscription_status not in {"canceled", "incomplete_expired"}:
                subscription_items = _event_value(subscription, "items")
                subscription_item_data = _event_value(subscription_items, "data")
                if (
                    not isinstance(subscription_item_data, (list, tuple))
                    or not subscription_item_data
                ):
                    raise HTTPException(
                        status_code=502,
                        detail="Existing Stripe subscription has no billable item.",
                    )
                subscription_item_id = _event_string(subscription_item_data[0], "id")
                if not subscription_item_id:
                    raise HTTPException(
                        status_code=502,
                        detail="Existing Stripe subscription has no billable item.",
                    )

                try:
                    updated_subscription = stripe_lib.Subscription.modify(
                        tenant.stripe_subscription_id,
                        items=[{"id": subscription_item_id, "price": price_id}],
                        proration_behavior="create_prorations",
                        metadata={"tenant_id": str(tenant_id), "plan_tier": plan_tier},
                    )
                except stripe_lib.error.StripeError as e:
                    raise HTTPException(
                        status_code=502,
                        detail="Unable to update the existing Stripe subscription.",
                    ) from e

                tenant.plan_tier = plan_tier
                updated_status = _event_string(updated_subscription, "status")
                status_map = {
                    "trialing": "trial",
                    "active": "active",
                    "past_due": "past_due",
                    "unpaid": "past_due",
                    "canceled": "canceled",
                    "incomplete_expired": "expired",
                }
                if updated_status in status_map:
                    tenant.subscription_status = status_map[updated_status]
                await session.flush()
                return {"url": updated_url, "changed": True}

            # Stripe has removed the subscription. A new checkout is safe now.
            tenant.stripe_subscription_id = None

    if settings.stripe_mock_mode or not settings.stripe_secret_key:
        # Mock mode: return a fake URL
        fake_session_id = str(uuid.uuid4())
        return {
            "url": f"{settings.frontend_url}/billing?mock_session={fake_session_id}",
            "changed": False,
        }

    stripe_lib.api_key = settings.stripe_secret_key

    if not tenant.stripe_customer_id:
        customer = stripe_lib.Customer.create(
            metadata={"tenant_id": str(tenant_id)},
        )
        tenant.stripe_customer_id = customer.id
        await session.flush()

    checkout_session = stripe_lib.checkout.Session.create(
        customer=tenant.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.frontend_url}/billing?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.frontend_url}/billing?canceled=true",
        metadata={"tenant_id": str(tenant_id), "plan_tier": plan_tier},
        subscription_data={"metadata": {"tenant_id": str(tenant_id), "plan_tier": plan_tier}},
    )

    return {"url": checkout_session.url, "changed": False}


# ── Stripe Webhook ─────────────────────────────────────────────────────


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    settings: Annotated[BillingSettings, Depends(get_settings)],
) -> dict:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if settings.stripe_mock_mode:
        # Mock mode: process the event directly from body
        try:
            event_data = json.loads(payload)
            if not isinstance(event_data, dict):
                return {"status": "ignored"}
            event_type = event_data.get("type", "")
            event_obj = event_data.get("data", {}).get("object", {})
        except (json.JSONDecodeError, AttributeError, TypeError):
            return {"status": "ignored"}
    else:
        if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
            raise HTTPException(status_code=503, detail="Stripe webhook is not configured.")
        try:
            stripe_lib.api_key = settings.stripe_secret_key
            event = stripe_lib.Webhook.construct_event(
                payload, sig_header or "", settings.stripe_webhook_secret
            )
        except (ValueError, stripe_lib.error.SignatureVerificationError) as e:
            raise HTTPException(status_code=401, detail="Invalid signature") from e
        event_type = event.type
        event_obj = event.data.object

    tenant = await _find_tenant_for_event(session, event_obj)
    metadata = _event_metadata(event_obj)

    if event_type == "checkout.session.completed":
        if tenant:
            tenant.plan_tier = _stored_plan_tier(metadata.get("plan_tier")).value
            tenant.subscription_status = "active"
            tenant.stripe_customer_id = _event_string(event_obj, "customer")
            tenant.stripe_subscription_id = _event_string(event_obj, "subscription")
            tenant.trial_ends_at = None
            await session.flush()

    elif event_type == "customer.subscription.updated":
        if tenant:
            plan_tier = metadata.get("plan_tier")
            if plan_tier is not None:
                tenant.plan_tier = _stored_plan_tier(plan_tier).value
            status = _event_string(event_obj, "status")
            status_map = {
                "trialing": "trial",
                "active": "active",
                "past_due": "past_due",
                "unpaid": "past_due",
                "canceled": "canceled",
                "incomplete_expired": "expired",
            }
            if status in status_map:
                tenant.subscription_status = status_map[status]
            await session.flush()

    elif event_type == "customer.subscription.deleted":
        if tenant:
            tenant.subscription_status = "canceled"
            await session.flush()

    elif event_type == "invoice.payment_failed":
        if tenant:
            tenant.subscription_status = "past_due"
            await session.flush()

    elif (
        event_type == "invoice.payment_succeeded"
        and tenant
        and tenant.subscription_status == "past_due"
    ):
        tenant.subscription_status = "active"
        await session.flush()

    return {"status": "ok"}


# ── Internal Plan Enforcement ──────────────────────────────────────────


@router.get("/internal/check-plan-limit")
async def check_plan_limit(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    settings: Annotated[BillingSettings, Depends(get_settings)],
) -> dict:
    internal_token = request.headers.get("X-Internal-Token", "")
    if not internal_token or internal_token != settings.tenant_internal_api_token:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required")

    resource = request.query_params.get("resource", "")
    current_count_str = request.query_params.get("current_count", "0")
    current_count = int(current_count_str)

    tenant_uuid = uuid.UUID(tenant_id)
    stmt = select(TenantModel).where(TenantModel.id == tenant_uuid)
    result = await session.execute(stmt)
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    plan = _stored_plan_tier(tenant.plan_tier)
    limits = PLAN_LIMITS[plan]

    now = datetime.now(UTC)
    if (
        tenant.subscription_status == "trial"
        and tenant.trial_ends_at
        and tenant.trial_ends_at < now
    ):
        tenant.subscription_status = "expired"
        tenant.plan_tier = PlanTier.STARTER.value
        plan = PlanTier.STARTER
        limits = PLAN_LIMITS[PlanTier.STARTER]
        await session.flush()

    if resource == "invoices":
        limit = limits.get("max_monthly_invoices")
    elif resource == "users":
        limit = limits.get("max_users")
    else:
        return {"allowed": True, "limit": None, "current": current_count}

    allowed = limit is None or current_count < limit
    return {"allowed": allowed, "limit": limit, "current": current_count}
