"""Domain exceptions and FastAPI exception handlers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette import status


class DomainException(Exception):
    """Base exception for all domain-level errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class NotFoundError(DomainException):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Resource not found."


class UnauthorizedError(DomainException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Not authenticated."


class ForbiddenError(DomainException):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Permission denied."


class ConflictError(DomainException):
    status_code = status.HTTP_409_CONFLICT
    detail = "Resource already exists."


class ValidationError(DomainException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    detail = "Validation failed."


class BadRequestError(DomainException):
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Bad request."


class ServiceUnavailableError(DomainException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail = "Service temporarily unavailable."


def _handler(request: Exception, exc: DomainException) -> JSONResponse:  # type: ignore[override]
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all domain exception handlers on a FastAPI application."""
    for exc_cls in (
        NotFoundError,
        UnauthorizedError,
        ForbiddenError,
        ConflictError,
        BadRequestError,
        ValidationError,
        ServiceUnavailableError,
    ):
        app.add_exception_handler(exc_cls, _handler)  # type: ignore[arg-type]


# Backwards-compatible alias used by some services
setup_exception_handlers = register_exception_handlers
