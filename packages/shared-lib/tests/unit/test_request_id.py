"""Unit tests for accounting_shared.middleware.request_id module."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.requests import Request
from starlette.testclient import TestClient

from accounting_shared.middleware.request_id import RequestIDMiddleware


class TestRequestIDMiddleware:
    """Tests for RequestIDMiddleware."""

    def test_middleware_propagates_existing_request_id(self):
        """Middleware should propagate existing X-Request-ID header."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {"request_id": request.state.request_id}

        client = TestClient(app)
        request_id = "test-request-id-123"
        response = client.get("/test", headers={"X-Request-ID": request_id})

        assert response.status_code == 200
        assert response.json()["request_id"] == request_id
        assert response.headers["X-Request-ID"] == request_id

    def test_middleware_generates_request_id_when_missing(self):
        """Middleware should generate UUID when X-Request-ID header is missing."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {"request_id": request.state.request_id}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        request_id = response.json()["request_id"]

        # Should be a valid UUID hex (32 characters)
        assert len(request_id) == 32
        # Should be valid hex string
        assert all(c in "0123456789abcdef" for c in request_id)
        # Should match response header
        assert response.headers["X-Request-ID"] == request_id

    def test_middleware_sets_request_state(self):
        """Middleware should set request.state.request_id."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {
                "has_request_id": hasattr(request.state, "request_id"),
                "request_id": request.state.request_id,
            }

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        data = response.json()
        assert data["has_request_id"] is True
        assert data["request_id"] is not None

    def test_middleware_response_has_request_id_header(self):
        """Middleware should add X-Request-ID header to response."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers

    def test_middleware_preserves_request_id_across_requests(self):
        """Each request should have its own unique request ID."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {"request_id": request.state.request_id}

        client = TestClient(app)

        # Make two requests
        response1 = client.get("/test")
        response2 = client.get("/test")

        request_id1 = response1.json()["request_id"]
        request_id2 = response2.json()["request_id"]

        # Should have different request IDs
        assert request_id1 != request_id2

    def test_middleware_with_custom_request_id_format(self):
        """Middleware should accept any string as X-Request-ID."""
        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)

        @app.get("/test")
        async def test_endpoint(request: Request):
            return {"request_id": request.state.request_id}

        client = TestClient(app)

        # Test with various formats
        test_ids = [
            "simple-id",
            "uuid-style-123e4567-e89b-12d3-a456-426614174000",
            "timestamp-20240101120000",
            "custom-format/with/slashes",
        ]

        for request_id in test_ids:
            response = client.get("/test", headers={"X-Request-ID": request_id})
            assert response.status_code == 200
            assert response.json()["request_id"] == request_id
            assert response.headers["X-Request-ID"] == request_id
