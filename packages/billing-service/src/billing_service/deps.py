"""FastAPI dependencies for billing-service."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from functools import lru_cache

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.database import get_session
from accounting_shared.exceptions import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from accounting_shared.http_internal import post_json
from accounting_shared.middleware.tenant_context import get_current_tenant_id
from accounting_shared.types import TenantId, UserId
from billing_service.config import BillingSettings

security_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_settings() -> BillingSettings:
    return BillingSettings()


async def get_access_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> dict[str, object]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Not authenticated.")
    settings = get_settings()
    try:
        return jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise UnauthorizedError("Not authenticated.") from e


async def get_current_user_id(
    payload: dict[str, object] = Depends(get_access_token_payload),
) -> UserId:
    if payload.get("type") != "access":
        raise UnauthorizedError("Not authenticated.")
    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Not authenticated.")
    try:
        return UserId(uuid.UUID(str(sub)))
    except ValueError as e:
        raise UnauthorizedError("Not authenticated.") from e


def require_tenant_id() -> TenantId:
    from accounting_shared.exceptions import ValidationError

    raw = get_current_tenant_id()
    if raw is None:
        raise ValidationError("X-Tenant-ID header is required.")
    return TenantId(raw)


async def get_current_tenant_id_str(
    tenant_id: TenantId = Depends(require_tenant_id),
) -> str:
    return str(tenant_id)


async def authorize_via_tenant_service(
    *,
    settings: BillingSettings,
    user_id: UserId,
    tenant_id: TenantId,
    permission: str,
) -> None:
    """Delegate billing tenant access checks to tenant-service."""
    token = (settings.tenant_internal_api_token or "").strip()
    if not token:
        raise ServiceUnavailableError("RBAC is not configured for this service.")

    base = (settings.tenant_service_url or "").strip().rstrip("/")
    if not base:
        raise ServiceUnavailableError("Tenant service URL is not configured.")

    try:
        status_code, data = await post_json(
            f"{base}/internal/authorization/check",
            headers={"X-Internal-Token": token},
            body={
                "user_id": str(user_id),
                "tenant_id": str(tenant_id),
                "permission": permission,
            },
        )
    except OSError as e:
        raise ServiceUnavailableError("Unable to reach tenant authorization service.") from e

    if status_code == 401:
        raise ServiceUnavailableError("Tenant authorization service rejected the internal token.")
    if status_code != 200 or not isinstance(data, dict):
        detail = data if isinstance(data, str) else str(data)
        raise ServiceUnavailableError(
            f"Tenant authorization service returned HTTP {status_code}: {detail}"
        )
    if data.get("allowed") is True:
        return

    reason = data.get("reason")
    if reason == "tenant_not_found":
        raise NotFoundError("Tenant not found.")
    if reason == "not_member":
        raise ForbiddenError("Not a member of this tenant.")
    raise ForbiddenError("You do not have permission for this action.")


class RequireBillingPermission:
    """Require an authenticated member with the requested tenant permission."""

    def __init__(self, permission: str) -> None:
        if not permission:
            raise ValueError("Permission is required.")
        self.permission = permission

    async def __call__(
        self,
        tenant_id: TenantId = Depends(require_tenant_id),
        user_id: UserId = Depends(get_current_user_id),
        settings: BillingSettings = Depends(get_settings),
    ) -> None:
        await authorize_via_tenant_service(
            settings=settings,
            user_id=user_id,
            tenant_id=tenant_id,
            permission=self.permission,
        )


async def get_async_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    factory = request.app.state.session_factory
    async for session in get_session(factory):
        yield session
