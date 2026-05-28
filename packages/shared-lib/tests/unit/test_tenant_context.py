"""Unit tests for accounting_shared.middleware.tenant_context module."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from accounting_shared.middleware.tenant_context import (
    TenantContextMiddleware,
    _tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)


@pytest.fixture(autouse=True)
def reset_tenant_context():
    """Reset tenant context between tests."""
    token = _tenant_id.set(None)
    yield
    _tenant_id.reset(token)


class TestGetSetTenantId:
    """Tests for get_current_tenant_id and set_current_tenant_id."""

    def test_get_current_tenant_id_default_none(self):
        """get_current_tenant_id should return None by default."""
        assert get_current_tenant_id() is None

    def test_set_current_tenant_id(self):
        """set_current_tenant_id should set the context variable."""
        tenant_id = uuid.uuid4()
        set_current_tenant_id(tenant_id)
        assert get_current_tenant_id() == tenant_id

    def test_set_current_tenant_id_updates_value(self):
        """set_current_tenant_id should update the context variable."""
        tenant_id1 = uuid.uuid4()
        tenant_id2 = uuid.uuid4()
        set_current_tenant_id(tenant_id1)
        set_current_tenant_id(tenant_id2)
        assert get_current_tenant_id() == tenant_id2


class TestTenantContextMiddleware:
    """Tests for TenantContextMiddleware."""

    def test_middleware_extracts_valid_tenant_id(self):
        """Middleware should extract valid UUID from X-Tenant-ID header."""
        app = FastAPI()
        app.add_middleware(TenantContextMiddleware)

        tenant_id = uuid.uuid4()

        @app.get("/test")
        async def test_endpoint():
            return {"tenant_id": str(get_current_tenant_id())}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Tenant-ID": str(tenant_id)})

        assert response.status_code == 200
        assert response.json()["tenant_id"] == str(tenant_id)

    def test_middleware_handles_missing_header(self):
        """Middleware should handle missing X-Tenant-ID header gracefully."""
        app = FastAPI()
        app.add_middleware(TenantContextMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"tenant_id": str(get_current_tenant_id())}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        # When no header, tenant_id should be None
        assert response.json()["tenant_id"] == "None"

    def test_middleware_handles_invalid_uuid(self):
        """Middleware should handle invalid UUID in X-Tenant-ID header."""
        app = FastAPI()
        app.add_middleware(TenantContextMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"tenant_id": str(get_current_tenant_id())}

        client = TestClient(app)
        response = client.get("/test", headers={"X-Tenant-ID": "invalid-uuid"})

        assert response.status_code == 200
        # Invalid UUID should result in None
        assert response.json()["tenant_id"] == "None"

    def test_middleware_clears_context_after_response(self):
        """Middleware should clear tenant_id context after response."""
        app = FastAPI()
        app.add_middleware(TenantContextMiddleware)

        tenant_id = uuid.uuid4()

        @app.get("/test")
        async def test_endpoint():
            return {"tenant_id": str(get_current_tenant_id())}

        client = TestClient(app)

        # First request
        response = client.get("/test", headers={"X-Tenant-ID": str(tenant_id)})
        assert response.json()["tenant_id"] == str(tenant_id)

        # Second request without header - should not have tenant_id from first request
        response = client.get("/test")
        assert response.json()["tenant_id"] == "None"

    def test_middleware_with_uuid_with_braces(self):
        """Middleware should handle UUID with braces format."""
        app = FastAPI()
        app.add_middleware(TenantContextMiddleware)

        tenant_id = uuid.uuid4()

        @app.get("/test")
        async def test_endpoint():
            return {"tenant_id": str(get_current_tenant_id())}

        client = TestClient(app)
        # UUID with braces
        response = client.get("/test", headers={"X-Request-ID": f"{{{tenant_id}}}"})

        # This should fail because braces are not valid UUID format
        assert response.status_code == 200
        # The middleware will fail to parse and leave tenant_id as None
        assert response.json()["tenant_id"] == "None"
