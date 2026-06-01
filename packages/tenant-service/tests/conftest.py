from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from accounting_shared.types import TenantId

from tenant_service.deps import get_tenant_service
from tenant_service.main import create_app
from tenant_service.modules.tenants.application.services import TenantService
from tenant_service.modules.tenants.infrastructure.repository import (
    SqlAlchemyTenantRepository,
)


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def mock_repository() -> MagicMock:
    return MagicMock(spec=SqlAlchemyTenantRepository)


@pytest.fixture
def tenant_service(mock_repository: MagicMock) -> TenantService:
    settings = MagicMock()
    settings.default_coa_seed = False
    return TenantService(mock_repository, settings)


@pytest_asyncio.fixture
async def client(app: FastAPI, tenant_service: TenantService) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_tenant_service] = lambda: tenant_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def sample_tenant_id() -> TenantId:
    return TenantId("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def sample_user_id() -> TenantId:
    return TenantId("22222222-2222-2222-2222-222222222222")
