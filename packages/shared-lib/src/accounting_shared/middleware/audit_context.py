"""Request-scoped audit context — user, tenant, and request id (EPIC 11).

Populates a ``contextvars.ContextVar`` from the incoming request so that
audit log emission points can attribute entries without threading identity
parameters through every call. Must be registered *inside* (i.e. added after
in ``add_middleware`` order is irrelevant) ``TenantContextMiddleware`` and
``RequestIDMiddleware`` so those have already run when this middleware reads
the request.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from accounting_shared.middleware.tenant_context import get_current_tenant_id


@dataclass(frozen=True)
class AuditContext:
    """Identity and correlation data available to audit log emission points."""

    user_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    request_id: str | None = None


_audit_context: contextvars.ContextVar[AuditContext | None] = contextvars.ContextVar(
    "audit_context", default=None
)


def get_audit_context() -> AuditContext:
    """Return the audit context for the current request (or an empty one)."""
    value = _audit_context.get()
    return value if value is not None else AuditContext()


class AuditContextMiddleware(BaseHTTPMiddleware):
    """Extracts user/tenant/request identity into the request-scoped audit context.

    * ``user_id`` — from the ``sub`` claim of the Bearer JWT (``None`` when
      the token is missing, invalid, or not a JWT).
    * ``tenant_id`` — from the tenant context variable set by
      :class:`~accounting_shared.middleware.tenant_context.TenantContextMiddleware`.
    * ``request_id`` — from ``request.state.request_id`` set by
      :class:`~accounting_shared.middleware.request_id.RequestIDMiddleware`.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        jwt_secret: str = "",
        jwt_algorithm: str = "HS256",
    ) -> None:
        super().__init__(app)
        self._jwt_secret = jwt_secret
        self._jwt_algorithm = jwt_algorithm

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        _audit_context.set(
            AuditContext(
                user_id=self._extract_user_id(request),
                tenant_id=get_current_tenant_id(),
                request_id=getattr(request.state, "request_id", None),
            )
        )
        try:
            response = await call_next(request)
        finally:
            _audit_context.set(AuditContext())
        return response

    def _extract_user_id(self, request: Request) -> uuid.UUID | None:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        if not token or not self._jwt_secret:
            return None
        try:
            payload: dict[str, object] = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self._jwt_algorithm],
            )
        except JWTError:
            return None
        sub = payload.get("sub")
        if not sub:
            return None
        try:
            return uuid.UUID(str(sub))
        except ValueError:
            return None
