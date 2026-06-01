"""Test configuration for audit-service."""
from __future__ import annotations

import pytest
from fastapi import FastAPI

from audit_service.main import app as _app


@pytest.fixture
def app() -> FastAPI:
    """Return the FastAPI application instance."""
    return _app
