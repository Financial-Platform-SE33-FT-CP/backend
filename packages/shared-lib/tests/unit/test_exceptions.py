"""Unit tests for accounting_shared.exceptions module."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette import status
from starlette.testclient import TestClient

from accounting_shared.exceptions import (
    BadRequestError,
    ConflictError,
    DomainException,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
    _handler,
    register_exception_handlers,
)


class TestDomainException:
    """Tests for the base DomainException class."""

    def test_default_status_code(self):
        """DomainException should have 500 as default status code."""
        exc = DomainException()
        assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_default_detail_message(self):
        """DomainException should have default detail message."""
        exc = DomainException()
        assert exc.detail == "An unexpected error occurred."

    def test_custom_detail_message(self):
        """DomainException should accept custom detail message."""
        exc = DomainException(detail="Custom error message")
        assert exc.detail == "Custom error message"

    def test_is_exception_subclass(self):
        """DomainException should be a subclass of Exception."""
        assert issubclass(DomainException, Exception)

    def test_str_representation(self):
        """DomainException str representation should be the detail message."""
        exc = DomainException(detail="Test error")
        assert str(exc) == "Test error"


class TestExceptionSubclasses:
    """Tests for all exception subclasses."""

    @pytest.mark.parametrize(
        "exc_class,expected_status,expected_default_detail",
        [
            (NotFoundError, status.HTTP_404_NOT_FOUND, "Resource not found."),
            (UnauthorizedError, status.HTTP_401_UNAUTHORIZED, "Not authenticated."),
            (ForbiddenError, status.HTTP_403_FORBIDDEN, "Permission denied."),
            (ConflictError, status.HTTP_409_CONFLICT, "Resource already exists."),
            (ValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT, "Validation failed."),
            (BadRequestError, status.HTTP_400_BAD_REQUEST, "Bad request."),
            (
                ServiceUnavailableError,
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Service temporarily unavailable.",
            ),
        ],
    )
    def test_exception_subclass_defaults(self, exc_class, expected_status, expected_default_detail):
        """Each exception subclass should have correct status code and default detail."""
        exc = exc_class()
        assert exc.status_code == expected_status
        assert exc.detail == expected_default_detail

    @pytest.mark.parametrize(
        "exc_class",
        [
            NotFoundError,
            UnauthorizedError,
            ForbiddenError,
            ConflictError,
            ValidationError,
            BadRequestError,
            ServiceUnavailableError,
        ],
    )
    def test_exception_subclass_custom_detail(self, exc_class):
        """Each exception subclass should accept custom detail message."""
        custom_message = f"Custom {exc_class.__name__} error"
        exc = exc_class(detail=custom_message)
        assert exc.detail == custom_message
        assert str(exc) == custom_message

    @pytest.mark.parametrize(
        "exc_class",
        [
            NotFoundError,
            UnauthorizedError,
            ForbiddenError,
            ConflictError,
            ValidationError,
            BadRequestError,
            ServiceUnavailableError,
        ],
    )
    def test_exception_subclass_is_domain_exception(self, exc_class):
        """Each exception subclass should be a subclass of DomainException."""
        assert issubclass(exc_class, DomainException)


class TestExceptionHandler:
    """Tests for the exception handler function."""

    def test_handler_returns_json_response(self):
        """_handler should return a JSONResponse."""
        exc = NotFoundError()
        response = _handler(None, exc)
        assert isinstance(response, JSONResponse)

    def test_handler_returns_correct_status_code(self):
        """_handler should return response with exception's status code."""
        exc = NotFoundError()
        response = _handler(None, exc)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_handler_returns_correct_content(self):
        """_handler should return response with exception's detail in content."""
        exc = NotFoundError(detail="Custom not found")
        response = _handler(None, exc)
        # JSONResponse wraps content, we need to check the body
        assert b'"Custom not found"' in response.body

    @pytest.mark.parametrize(
        "exc_class,expected_status",
        [
            (NotFoundError, status.HTTP_404_NOT_FOUND),
            (UnauthorizedError, status.HTTP_401_UNAUTHORIZED),
            (ForbiddenError, status.HTTP_403_FORBIDDEN),
            (ConflictError, status.HTTP_409_CONFLICT),
            (ValidationError, status.HTTP_422_UNPROCESSABLE_CONTENT),
            (BadRequestError, status.HTTP_400_BAD_REQUEST),
            (ServiceUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE),
        ],
    )
    def test_handler_with_all_exception_types(self, exc_class, expected_status):
        """_handler should handle all exception types correctly."""
        exc = exc_class()
        response = _handler(None, exc)
        assert response.status_code == expected_status


class TestRegisterExceptionHandlers:
    """Tests for the register_exception_handlers function."""

    def test_register_exception_handlers_adds_handlers(self):
        """register_exception_handlers should add handlers for all exception types."""
        app = FastAPI()
        register_exception_handlers(app)

        # Check that exception handlers are registered
        # FastAPI stores exception handlers in app.exception_handlers
        assert NotFoundError in app.exception_handlers
        assert UnauthorizedError in app.exception_handlers
        assert ForbiddenError in app.exception_handlers
        assert ConflictError in app.exception_handlers
        assert ValidationError in app.exception_handlers
        assert BadRequestError in app.exception_handlers
        assert ServiceUnavailableError in app.exception_handlers

    def test_exception_handlers_work_in_fastapi_app(self):
        """Exception handlers should work correctly in a FastAPI application."""
        app = FastAPI()
        register_exception_handlers(app)

        @app.get("/test-not-found")
        async def test_not_found():
            raise NotFoundError(detail="Item not found")

        @app.get("/test-unauthorized")
        async def test_unauthorized():
            raise UnauthorizedError()

        @app.get("/test-forbidden")
        async def test_forbidden():
            raise ForbiddenError()

        @app.get("/test-conflict")
        async def test_conflict():
            raise ConflictError()

        @app.get("/test-validation")
        async def test_validation():
            raise ValidationError()

        @app.get("/test-bad-request")
        async def test_bad_request():
            raise BadRequestError()

        @app.get("/test-service-unavailable")
        async def test_service_unavailable():
            raise ServiceUnavailableError()

        client = TestClient(app)

        # Test each exception endpoint
        response = client.get("/test-not-found")
        assert response.status_code == 404
        assert response.json() == {"detail": "Item not found"}

        response = client.get("/test-unauthorized")
        assert response.status_code == 401
        assert response.json() == {"detail": "Not authenticated."}

        response = client.get("/test-forbidden")
        assert response.status_code == 403
        assert response.json() == {"detail": "Permission denied."}

        response = client.get("/test-conflict")
        assert response.status_code == 409
        assert response.json() == {"detail": "Resource already exists."}

        response = client.get("/test-validation")
        assert response.status_code == 422
        assert response.json() == {"detail": "Validation failed."}

        response = client.get("/test-bad-request")
        assert response.status_code == 400
        assert response.json() == {"detail": "Bad request."}

        response = client.get("/test-service-unavailable")
        assert response.status_code == 503
        assert response.json() == {"detail": "Service temporarily unavailable."}

    def test_setup_exception_handlers_alias(self):
        """setup_exception_handlers should be an alias for register_exception_handlers."""
        from accounting_shared.exceptions import setup_exception_handlers

        assert setup_exception_handlers is register_exception_handlers
