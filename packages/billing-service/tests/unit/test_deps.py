"""Unit tests for authentication, tenant context and delegated RBAC."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from accounting_shared.exceptions import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from accounting_shared.types import TenantId, UserId
from billing_service import deps
from billing_service.config import BillingSettings

USER_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _credentials(settings: BillingSettings, **claims: object) -> HTTPAuthorizationCredentials:
    payload = {
        "sub": str(USER_ID),
        "type": "access",
        "exp": 4_102_444_800,
        **claims,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_get_access_token_payload_accepts_valid_token(
    billing_settings: BillingSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: billing_settings)

    payload = await deps.get_access_token_payload(_credentials(billing_settings))

    assert payload["sub"] == str(USER_ID)
    assert payload["type"] == "access"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credentials",
    [
        None,
        HTTPAuthorizationCredentials(scheme="Basic", credentials="token"),
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt"),
    ],
)
async def test_get_access_token_payload_rejects_invalid_credentials(
    credentials: HTTPAuthorizationCredentials | None,
) -> None:
    with pytest.raises(UnauthorizedError, match="Not authenticated"):
        await deps.get_access_token_payload(credentials)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"sub": str(USER_ID)},
        {"type": "access"},
        {"type": "refresh", "sub": str(USER_ID)},
        {"type": "access", "sub": "not-a-uuid"},
    ],
)
async def test_get_current_user_id_requires_access_token(payload: dict[str, object]) -> None:
    with pytest.raises(UnauthorizedError, match="Not authenticated"):
        await deps.get_current_user_id(payload)


@pytest.mark.asyncio
async def test_get_current_user_id_returns_uuid() -> None:
    user_id = await deps.get_current_user_id({"type": "access", "sub": str(USER_ID)})

    assert user_id == UserId(USER_ID)


def test_require_billing_permission_requires_permission() -> None:
    with pytest.raises(ValueError, match="Permission is required"):
        deps.RequireBillingPermission("")


def test_require_tenant_id_requires_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "get_current_tenant_id", lambda: None)

    with pytest.raises(ValidationError, match="X-Tenant-ID header is required"):
        deps.require_tenant_id()


def test_require_tenant_id_returns_context_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "get_current_tenant_id", lambda: TENANT_ID)

    assert deps.require_tenant_id() == TenantId(TENANT_ID)


@pytest.mark.asyncio
async def test_authorize_via_tenant_service_sends_internal_request(
    billing_settings: BillingSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_json = AsyncMock(return_value=(200, {"allowed": True}))
    monkeypatch.setattr(deps, "post_json", post_json)

    await deps.authorize_via_tenant_service(
        settings=billing_settings,
        user_id=UserId(USER_ID),
        tenant_id=TenantId(TENANT_ID),
        permission="tenant:read",
    )

    post_json.assert_awaited_once_with(
        "http://tenant.test/internal/authorization/check",
        headers={"X-Internal-Token": "billing-test-internal-token"},
        body={
            "user_id": str(USER_ID),
            "tenant_id": str(TENANT_ID),
            "permission": "tenant:read",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings_kwargs, message",
    [
        ({"tenant_internal_api_token": ""}, "RBAC is not configured"),
        ({"tenant_service_url": ""}, "Tenant service URL is not configured"),
    ],
)
async def test_authorize_via_tenant_service_requires_configuration(
    billing_settings: BillingSettings,
    settings_kwargs: dict[str, str],
    message: str,
) -> None:
    settings = billing_settings.model_copy(update=settings_kwargs)

    with pytest.raises(ServiceUnavailableError, match=message):
        await deps.authorize_via_tenant_service(
            settings=settings,
            user_id=UserId(USER_ID),
            tenant_id=TenantId(TENANT_ID),
            permission="tenant:read",
        )


@pytest.mark.asyncio
async def test_authorize_via_tenant_service_maps_network_error(
    billing_settings: BillingSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_json = AsyncMock(side_effect=OSError("connection refused"))
    monkeypatch.setattr(deps, "post_json", post_json)

    with pytest.raises(ServiceUnavailableError, match="Unable to reach"):
        await deps.authorize_via_tenant_service(
            settings=billing_settings,
            user_id=UserId(USER_ID),
            tenant_id=TenantId(TENANT_ID),
            permission="tenant:read",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, data",
    [
        (401, {"detail": "unauthorized"}),
        (503, {"detail": "unavailable"}),
        (200, "not-json-object"),
    ],
)
async def test_authorize_via_tenant_service_rejects_bad_response(
    billing_settings: BillingSettings,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    data: object,
) -> None:
    monkeypatch.setattr(deps, "post_json", AsyncMock(return_value=(status_code, data)))

    with pytest.raises(ServiceUnavailableError):
        await deps.authorize_via_tenant_service(
            settings=billing_settings,
            user_id=UserId(USER_ID),
            tenant_id=TenantId(TENANT_ID),
            permission="tenant:read",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason, expected_exception",
    [
        ("tenant_not_found", NotFoundError),
        ("not_member", ForbiddenError),
        ("permission_denied", ForbiddenError),
    ],
)
async def test_authorize_via_tenant_service_maps_denials(
    billing_settings: BillingSettings,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    expected_exception: type[Exception],
) -> None:
    monkeypatch.setattr(
        deps,
        "post_json",
        AsyncMock(return_value=(200, {"allowed": False, "reason": reason})),
    )

    with pytest.raises(expected_exception):
        await deps.authorize_via_tenant_service(
            settings=billing_settings,
            user_id=UserId(USER_ID),
            tenant_id=TenantId(TENANT_ID),
            permission="tenant:update",
        )
