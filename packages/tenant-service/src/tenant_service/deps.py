from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from accounting_shared.exceptions import ForbiddenError, NotFoundError
from accounting_shared.rbac import TenantRole, role_has_permission
from accounting_shared.types import TenantId, UserId
from fastapi import Depends, HTTPException
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


async def get_access_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    settings: TenantSettings = Depends(get_settings),
) -> dict[str, object]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        return jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail="Not authenticated.") from e


async def get_current_user_id(
    payload: dict[str, object] = Depends(get_access_token_payload),
) -> UserId:
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Not authenticated.")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        return UserId(uuid.UUID(str(sub)))
    except ValueError as e:
        raise HTTPException(status_code=401, detail="Not authenticated.") from e


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
    return TenantService(repository, settings)


class RequireTenantPermissions:
    """Route-level RBAC: loads membership from DB and checks permission strings."""

    def __init__(self, *permissions: str) -> None:
        if not permissions:
            msg = "At least one permission is required."
            raise ValueError(msg)
        self.permissions = permissions

    async def __call__(
        self,
        request: Request,
        tenant_id: uuid.UUID,
        user_id: UserId = Depends(get_current_user_id),
        repo: SqlAlchemyTenantRepository = Depends(get_tenant_repository),
        session: AsyncSession = Depends(get_async_session),
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
                await repo.write_audit_rbac_denied(
                    tenant_id=tid,
                    user_id=user_id,
                    permission=";".join(self.permissions),
                    reason="not_member",
                    request_id=rid,
                    attempted_action=attempted_action,
                )
                await session.commit()
                raise ForbiddenError("Not a member of this tenant.")
            await repo.write_audit_rbac_denied(
                tenant_id=tid,
                user_id=user_id,
                permission=self.permissions[0],
                reason="permission_denied",
                request_id=rid,
                attempted_action=attempted_action,
            )
            await session.commit()
            raise ForbiddenError("You do not have permission for this action.")

        role = ev.role
        assert role is not None
        for perm in self.permissions[1:]:
            if not role_has_permission(role, perm):
                await repo.write_audit_rbac_denied(
                    tenant_id=tid,
                    user_id=user_id,
                    permission=perm,
                    reason="permission_denied",
                    request_id=rid,
                    attempted_action=attempted_action,
                )
                await session.commit()
                raise ForbiddenError("You do not have permission for this action.")
        return role
