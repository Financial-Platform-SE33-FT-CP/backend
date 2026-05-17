import asyncio
import importlib
import logging
import uuid
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Date, String, Table, Uuid

# Silence all logging during tests to avoid structlog version conflicts
logging.disable(logging.CRITICAL)


def _configure_env(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")


async def _create_all(engine: object) -> None:
    from sqlalchemy import Column, MetaData, text

    from ledger_service.modules.ledger.infrastructure.models import Base

    # Create stub tables for cross-service FK references
    metadata = Base.metadata
    _ = Table(
        "tenants",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("name", String(255)),
        extend_existing=True,
    )
    _ = Table(
        "chart_of_accounts",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("code", String(20)),
        Column("name", String(255)),
        extend_existing=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all, checkfirst=True)


TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ACCOUNT_1_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
ACCOUNT_2_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path.joinpath('ledger_test.sqlite').as_posix()}"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, sqlite_url: str) -> Iterator[TestClient]:
    _configure_env(monkeypatch, sqlite_url)

    from ledger_service import deps

    deps.get_settings.cache_clear()

    import ledger_service.main as main_mod

    importlib.reload(main_mod)

    with TestClient(main_mod.app) as tc:
        asyncio.run(_create_all(tc.app.state.engine))
        yield tc

    deps.get_settings.cache_clear()


@pytest.fixture
def tenant_id() -> str:
    return str(TENANT_ID)


@pytest.fixture
def valid_payload() -> dict:
    return {
        "entry_date": date.today().isoformat(),
        "reference": "JE-001",
        "description": "Test journal entry",
        "lines": [
            {
                "account_id": str(ACCOUNT_1_ID),
                "debit_amount": "100.00",
                "credit_amount": "0.00",
                "description": "Debit cash",
            },
            {
                "account_id": str(ACCOUNT_2_ID),
                "debit_amount": "0.00",
                "credit_amount": "100.00",
                "description": "Credit revenue",
            },
        ],
    }
