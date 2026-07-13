"""Unit tests for SqlAlchemyUserRepository with mocked session."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from accounting_shared.types import new_user_id
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.modules.auth.domain.entities import User
from auth_service.modules.auth.infrastructure.models import UserModel
from auth_service.modules.auth.infrastructure.repository import SqlAlchemyUserRepository


def _make_repo(session: AsyncSession | None = None) -> SqlAlchemyUserRepository:
    return SqlAlchemyUserRepository(session or AsyncMock(spec=AsyncSession))


def _mock_result(return_model: object | None) -> MagicMock:
    """Build a synchronous MagicMock chain mimicking SQLAlchemy Result.scalars().first()."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.first = MagicMock(return_value=return_model)
    result.scalars = MagicMock(return_value=scalars)
    return result


@pytest.mark.asyncio
async def test_get_by_email_found() -> None:
    session = AsyncMock(spec=AsyncSession)
    uid = new_user_id()
    now = datetime.now(UTC)
    model = UserModel(
        id=uid,
        email="get@example.com",
        hashed_password="hash",
        full_name="Test",
        email_verified=True,
        is_active=True,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    session.execute = AsyncMock(return_value=_mock_result(model))

    repo = _make_repo(session)
    user = await repo.get_by_email("get@example.com")
    assert user is not None
    assert user.email == "get@example.com"
    assert user.id == uid
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_email_not_found() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_mock_result(None))

    repo = _make_repo(session)
    user = await repo.get_by_email("missing@example.com")
    assert user is None


@pytest.mark.asyncio
async def test_get_by_id_found() -> None:
    session = AsyncMock(spec=AsyncSession)
    uid = new_user_id()
    now = datetime.now(UTC)
    model = UserModel(
        id=uid,
        email="byid@example.com",
        hashed_password="hash",
        full_name="Test",
        email_verified=True,
        is_active=True,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    session.execute = AsyncMock(return_value=_mock_result(model))

    repo = _make_repo(session)
    user = await repo.get_by_id(uid)
    assert user is not None
    assert user.id == uid
    assert user.email == "byid@example.com"


@pytest.mark.asyncio
async def test_get_by_id_not_found() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=_mock_result(None))

    repo = _make_repo(session)
    user = await repo.get_by_id(new_user_id())
    assert user is None


@pytest.mark.asyncio
async def test_add_new_user() -> None:
    session = AsyncMock(spec=AsyncSession)
    uid = new_user_id()
    now = datetime.now(UTC)
    user = User(
        id=uid,
        email="add@example.com",
        hashed_password="hash",
        full_name="Test User",
        email_verified=False,
        is_active=True,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )

    repo = _make_repo(session)
    added = await repo.add(user)
    session.add.assert_called_once()
    session.flush.assert_called_once()
    assert added.id == uid
    assert added.email == "add@example.com"


@pytest.mark.asyncio
async def test_update_existing_user() -> None:
    session = AsyncMock(spec=AsyncSession)
    uid = new_user_id()
    now = datetime.now(UTC)
    model = UserModel(
        id=uid,
        email="update@example.com",
        hashed_password="oldhash",
        full_name="Old Name",
        email_verified=False,
        is_active=True,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now - timedelta(hours=1),
        updated_at=now - timedelta(hours=1),
    )
    session.execute = AsyncMock(return_value=_mock_result(model))
    user = User(
        id=uid,
        email="update@example.com",
        hashed_password="newhash",
        full_name="Updated",
        email_verified=True,
        is_active=True,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    repo = _make_repo(session)
    updated = await repo.update(user)
    session.flush.assert_awaited_once()
    assert updated.email == "update@example.com"


@pytest.mark.asyncio
async def test_update_login_security_resets() -> None:
    session = AsyncMock(spec=AsyncSession)
    uid = new_user_id()
    now = datetime.now(UTC)
    model = UserModel(
        id=uid,
        email="loginsec@example.com",
        hashed_password="hash",
        full_name="Test",
        email_verified=True,
        is_active=True,
        failed_login_attempts=3,
        locked_until=now + timedelta(minutes=15),
        created_at=now,
        updated_at=now,
    )
    session.execute = AsyncMock(return_value=_mock_result(model))

    repo = _make_repo(session)
    await repo.update_login_security(uid, failed_attempts=0, locked_until=None)
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_login_security_locks() -> None:
    session = AsyncMock(spec=AsyncSession)
    uid = new_user_id()
    now = datetime.now(UTC)
    model = UserModel(
        id=uid,
        email="loginseclock@example.com",
        hashed_password="hash",
        full_name="Test",
        email_verified=True,
        is_active=True,
        failed_login_attempts=2,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    session.execute = AsyncMock(return_value=_mock_result(model))
    locked_until = now + timedelta(minutes=15)

    repo = _make_repo(session)
    await repo.update_login_security(uid, failed_attempts=5, locked_until=locked_until)
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_commit() -> None:
    session = AsyncMock(spec=AsyncSession)
    repo = _make_repo(session)
    await repo.commit()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user() -> None:
    session = AsyncMock(spec=AsyncSession)
    uid = new_user_id()
    now = datetime.now(UTC)
    model = UserModel(
        id=uid,
        email="delete@example.com",
        hashed_password="hash",
        full_name="Test",
        email_verified=False,
        is_active=True,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    session.execute = AsyncMock(return_value=_mock_result(model))
    user = User(
        id=uid,
        email="delete@example.com",
        hashed_password="hash",
        email_verified=False,
        failed_login_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )

    repo = _make_repo(session)
    await repo.delete(user)
    session.delete.assert_called_once()
    session.flush.assert_called_once()
