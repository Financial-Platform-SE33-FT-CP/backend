"""Dependency injection — database session factory, JWT user, delegated tenant RBAC (US-3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from functools import lru_cache

from accounting_shared.database import get_session
from accounting_shared.http_internal import post_json
from accounting_shared.exceptions import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from accounting_shared.middleware.tenant_context import get_current_tenant_id
from accounting_shared.types import TenantId, UserId
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from coa_service.config import COASettings
from coa_service.modules.coa.application.services import COAService
from coa_service.modules.coa.domain.repository import AccountRepository
from coa_service.modules.coa.infrastructure.repository import SqlAlchemyAccountRepository

_settings: COASettings | None = None
_engine = None
_session_factory = None

security_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_settings() -> COASettings:
    return COASettings()


async def get_access_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    settings: COASettings = Depends(get_settings),
) -> dict[str, object]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Not authenticated.")
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
    raw = get_current_tenant_id()
    if raw is None:
        raise ValidationError("X-Tenant-ID header is required.")
    return TenantId(raw)


async def authorize_via_tenant_service(
    *,
    settings: COASettings,
    user_id: UserId,
    tenant_id: TenantId,
    permission: str,
) -> None:
    """Delegate permission check to tenant-service.

    Membership and role remain the single source of truth there (US-3).
    """
    token = (settings.tenant_internal_api_token or "").strip()
    if not token:
        raise ServiceUnavailableError("RBAC is not configured for this service.")

    base = (settings.tenant_service_url or "").strip().rstrip("/")
    if not base:
        raise ServiceUnavailableError("Tenant service URL is not configured.")

    url = f"{base}/internal/authorization/check"

    try:
        status_code, data = await post_json(
            url,
            headers={"X-Internal-Token": token},
            body={
                "user_id": str(user_id),
                "tenant_id": str(tenant_id),
                "permission": permission,
            },
        )
    except OSError as e:
        msg = "Unable to reach tenant authorization service."
        raise ServiceUnavailableError(msg) from e

    if status_code == 401:
        raise ServiceUnavailableError("Tenant authorization service rejected the internal token.")
    if status_code != 200:
        detail = data if isinstance(data, str) else str(data)
        raise ServiceUnavailableError(
            f"Tenant authorization service returned HTTP {status_code}: {detail}"
        )
    if not isinstance(data, dict):
        raise ServiceUnavailableError("Tenant authorization service returned an invalid response.")
    if data.get("allowed") is True:
        return

    reason = data.get("reason")
    if reason == "tenant_not_found":
        raise NotFoundError("Tenant not found.")
    if reason == "not_member":
        raise ForbiddenError("Not a member of this tenant.")
    raise ForbiddenError("You do not have permission for this action.")


class RequireCoaPermission:
    """Route dependency: JWT user + X-Tenant-ID + delegated RBAC for one permission string."""

    def __init__(self, permission: str) -> None:
        if not permission:
            msg = "Permission is required."
            raise ValueError(msg)
        self.permission = permission

    async def __call__(
        self,
        tenant_id: TenantId = Depends(require_tenant_id),
        user_id: UserId = Depends(get_current_user_id),
        settings: COASettings = Depends(get_settings),
    ) -> None:
        await authorize_via_tenant_service(
            settings=settings,
            user_id=user_id,
            tenant_id=tenant_id,
            permission=self.permission,
        )


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    global _engine, _session_factory

    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=settings.debug)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async for session in get_session(_session_factory):
        yield session


async def get_coa_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AccountRepository:
    return SqlAlchemyAccountRepository(session)


async def get_coa_service(
    repository: AccountRepository = Depends(get_coa_repository),
) -> COAService:
    return COAService(repository)
