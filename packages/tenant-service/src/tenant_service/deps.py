from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from accounting_shared.audit_client import AuditHttpClient, CreateAuditLogDTO
from accounting_shared.exceptions import ForbiddenError, NotFoundError
from accounting_shared.rbac import TenantRole, role_has_permission
from accounting_shared.types import TenantId, UserId
from fastapi import Depends, Header, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from .config import TenantSettings
from .modules.tenants.application.authorization import evaluate_tenant_permission
from .modules.tenants.application.services import TenantService
from .modules.tenants.infrastructure.repository import SqlAlchemyTenantRepository

_settings: TenantSettings | None = None
_engine = None
_session_factory = None

security_scheme = HTTPBearer(auto_error=False)
internal_token_header = APIKeyHeader(name="X-Internal-Token", auto_error=False)


def get_settings() -> TenantSettings:
    global _settings
    if _settings is None:
        _settings = TenantSettings()
    return _settings


def get_audit_client() -> AuditHttpClient:
    """Build the fire-and-forget audit log client from service settings."""
    settings = get_settings()
    return AuditHttpClient(
        audit_service_url=settings.audit_service_url,
        internal_token=settings.audit_internal_api_token or settings.internal_api_token,
    )


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session with commit/rollback on exit."""
    global _engine, _session_factory

    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        _engine = create_async_engine(url, echo=settings.debug)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def _jwt_payload_from_bearer(
    credentials: HTTPAuthorizationCredentials | None,
    settings: TenantSettings,
) -> dict[str, object] | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        payload: dict[str, object] = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Not authenticated.") from None


async def get_access_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    settings: TenantSettings = Depends(get_settings),
) -> dict[str, object]:
    payload = _jwt_payload_from_bearer(credentials, settings)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return payload


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    settings: TenantSettings = Depends(get_settings),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> UserId:
    payload = _jwt_payload_from_bearer(credentials, settings)
    if payload is not None:
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Not authenticated.")
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Not authenticated.")
        try:
            return UserId(uuid.UUID(str(sub)))
        except ValueError as e:
            raise HTTPException(status_code=401, detail="Not authenticated.") from e

    if settings.trust_x_user_id_header and x_user_id and x_user_id.strip():
        try:
            return UserId(uuid.UUID(x_user_id.strip()))
        except ValueError as e:
            raise HTTPException(
                status_code=401,
                detail="Invalid X-User-Id.",
            ) from e

    raise HTTPException(status_code=401, detail="Not authenticated.")


async def verify_internal_service_token(
    token: str | None = Depends(internal_token_header),
    settings: TenantSettings = Depends(get_settings),
) -> None:
    expected = (settings.internal_api_token or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")
    if token != expected:
        raise HTTPException(status_code=401, detail="Not authenticated.")


async def get_tenant_repository(
    session: AsyncSession = Depends(get_async_session),
) -> SqlAlchemyTenantRepository:
    return SqlAlchemyTenantRepository(session)


async def get_tenant_service(
    repository: SqlAlchemyTenantRepository = Depends(get_tenant_repository),
) -> TenantService:
    settings = get_settings()
    return TenantService(repository, settings, audit_client=get_audit_client())


class RequireTenantPermissions:
    """Route-level RBAC: loads membership from DB and checks permission strings."""

    def __init__(self, *permissions: str) -> None:
        if not permissions:
            msg = "At least one permission is required."
            raise ValueError(msg)
        self.permissions = permissions

    def _write_rbac_denied(
        self,
        *,
        tid: TenantId,
        user_id: UserId,
        permission: str,
        reason: str,
        request_id: str | None,
        attempted_action: str | None,
    ) -> None:
        """Emit a fire-and-forget audit entry for a denied RBAC check."""
        get_audit_client().log_in_background(
            CreateAuditLogDTO(
                tenant_id=tid,
                user_id=user_id,
                action="RBAC_DENIED",
                entity_type="rbac",
                entity_id=str(tid),
                changes={
                    "result": "denied",
                    "permission": permission,
                    "reason": reason,
                    "request_id": request_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "attempted_action": attempted_action,
                },
            )
        )

    async def __call__(
        self,
        request: Request,
        tenant_id: uuid.UUID,
        user_id: UserId = Depends(get_current_user_id),
        repo: SqlAlchemyTenantRepository = Depends(get_tenant_repository),
    ) -> TenantRole:
        tid = TenantId(tenant_id)
        req_id = getattr(request.state, "request_id", None)
        rid = req_id if isinstance(req_id, str) else None
        attempted_action = f"{request.method} {request.url.path}"

        ev = await evaluate_tenant_permission(
            repo, tenant_id=tid, user_id=user_id, permission=self.permissions[0]
        )
        if not ev.allowed:
            if ev.reason == "tenant_not_found":
                raise NotFoundError("Tenant not found.")
            if ev.reason == "not_member":
                self._write_rbac_denied(
                    tid=tid,
                    user_id=user_id,
                    permission=";".join(self.permissions),
                    reason="not_member",
                    request_id=rid,
                    attempted_action=attempted_action,
                )
                raise ForbiddenError("Not a member of this tenant.")
            self._write_rbac_denied(
                tid=tid,
                user_id=user_id,
                permission=self.permissions[0],
                reason="permission_denied",
                request_id=rid,
                attempted_action=attempted_action,
            )
            raise ForbiddenError("You do not have permission for this action.")

        role = ev.role
        assert role is not None
        for perm in self.permissions[1:]:
            if not role_has_permission(role, perm):
                self._write_rbac_denied(
                    tid=tid,
                    user_id=user_id,
                    permission=perm,
                    reason="permission_denied",
                    request_id=rid,
                    attempted_action=attempted_action,
                )
                raise ForbiddenError("You do not have permission for this action.")
        return role
