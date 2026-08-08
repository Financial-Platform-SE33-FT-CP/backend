"""Shared fixtures for billing-service unit and API tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import Column, MetaData, String, Table
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from billing_service import deps
from billing_service.config import BillingSettings
from billing_service.main import app
from tenant_service.modules.tenants.infrastructure.models import TenantModel

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
USER_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
JWT_SECRET = "billing-test-jwt-secret"
INTERNAL_TOKEN = "billing-test-internal-token"


usage_metadata = MetaData()
Table(
    "invoices",
    usage_metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("created_at", String(64), nullable=False),
)
Table(
    "tenant_users",
    usage_metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("status", String(32), nullable=False),
)


@pytest.fixture
def billing_settings() -> BillingSettings:
    return BillingSettings(
        database_url="sqlite+aiosqlite://",
        jwt_secret=JWT_SECRET,
        tenant_internal_api_token=INTERNAL_TOKEN,
        tenant_service_url="http://tenant.test",
        stripe_mock_mode=True,
        frontend_url="http://frontend.test",
        stripe_price_ids={
            "starter_monthly": "price_starter",
            "growth_monthly": "price_growth",
            "pro_monthly": "price_pro",
        },
    )


@pytest_asyncio.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    database_path = tmp_path / "billing.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(TenantModel.__table__.create)
        await connection.run_sync(usage_metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def tenant_factory():
    def _factory(
        *,
        tenant_id: uuid.UUID = TENANT_ID,
        plan_tier: str = "starter",
        subscription_status: str = "trial",
        trial_ends_at: datetime | None = None,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
    ) -> TenantModel:
        now = datetime.now(UTC)
        return TenantModel(
            id=tenant_id,
            name="Billing Test Tenant",
            base_currency="SGD",
            financial_year_start_month=1,
            financial_year_start_day=1,
            status="active",
            created_by_user_id=USER_ID,
            created_at=now,
            updated_at=now,
            plan_tier=plan_tier,
            subscription_status=subscription_status,
            trial_ends_at=trial_ends_at,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
        )

    return _factory


@pytest.fixture
def persist_tenant(session_factory: async_sessionmaker[AsyncSession]):
    async def _persist(tenant: TenantModel) -> TenantModel:
        async with session_factory() as session:
            session.add(tenant)
            await session.commit()
        return tenant

    return _persist


@pytest.fixture
def auth_headers(billing_settings: BillingSettings) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(USER_ID),
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        billing_settings.jwt_secret,
        algorithm=billing_settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    billing_settings: BillingSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    original_get_settings = deps.get_settings

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def allow_authorization(**_: object) -> None:
        return None

    app.dependency_overrides[original_get_settings] = lambda: billing_settings
    app.dependency_overrides[deps.get_async_session] = override_session
    monkeypatch.setattr(deps, "get_settings", lambda: billing_settings)
    monkeypatch.setattr(deps, "authorize_via_tenant_service", allow_authorization)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://billing.test",
    ) as async_client:
        yield async_client

    app.dependency_overrides.clear()
