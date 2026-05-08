"""Request-ID middleware — propagates or generates ``X-Request-ID``."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that ensures every request has a unique id.

    * Propagates an incoming ``X-Request-ID`` header if present.
    * Generates a ``uuid4`` string if the header is missing.
    * Sets ``request.state.request_id`` for downstream use.
    * Writes the id back on the response ``X-Request-ID`` header.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id: str = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
