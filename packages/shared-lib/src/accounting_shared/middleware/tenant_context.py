"""Tenant context middleware — extracts ``X-Tenant-ID`` into a context variable."""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Awaitable
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_tenant_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "tenant_id", default=None
)


def get_current_tenant_id() -> uuid.UUID | None:
    """Return the tenant id set for the current request context, or *None*."""
    return _tenant_id.get()


def set_current_tenant_id(tenant_id: uuid.UUID) -> None:
    """Set the tenant id for the current request context."""
    _tenant_id.set(tenant_id)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that reads ``X-Tenant-ID`` from request headers.

    Stores the parsed UUID in a ``contextvars.ContextVar`` so that it is
    available throughout the request lifecycle without passing it explicitly.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw = request.headers.get("X-Tenant-ID")
        if raw is not None:
            try:
                tenant_id = uuid.UUID(raw)
            except ValueError:
                tenant_id = None
            if tenant_id is not None:
                set_current_tenant_id(tenant_id)
        # Clear after the response is built
        response = await call_next(request)
        _tenant_id.set(None)
        return response
