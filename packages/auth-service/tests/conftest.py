"""Pytest fixtures for auth-service tests."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from accounting_shared.types import UserId, new_user_id

from auth_service.config import AuthSettings
from auth_service.modules.auth.domain.entities import User, VerificationToken
from auth_service.modules.auth.infrastructure.models import Base


@pytest.fixture
def test_settings() -> AuthSettings:
    """Return test-specific settings."""
    return AuthSettings(
        APP_ENV="test",
        DEBUG=True,
        LOG_LEVEL="DEBUG",
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/accounting_test",
        JWT_SECRET="test-secret-key-not-for-production",
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES=5,
        JWT_REFRESH_TOKEN_EXPIRE_DAYS=1,
        EMAIL_VERIFICATION_REQUIRED=True,
        BCRYPT_ROUNDS=4,  # Fast rounds for tests
    )


@pytest_asyncio.fixture
async def test_engine():
    """Create a test database engine."""
    engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/accounting_test",
        pool_size=5,
        max_overflow=0,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def test_user_repo() -> AsyncMock:
    """Return a mock user repository."""
    repo = AsyncMock()

    # Default return values
    test_user_id = new_user_id()
    test_user = User(
        id=test_user_id,
        email="test@example.com",
        hashed_password="$2b$12$" + "a" * 53,  # Placeholder bcrypt hash
        full_name="Test User",
        email_verified=True,
        is_active=True,
    )
    repo.get_by_id.return_value = test_user
    repo.get_by_email.return_value = test_user
    repo.add.return_value = test_user
    repo.update.return_value = test_user

    return repo
