from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from accounting_shared.exceptions import NotFoundError, ValidationError
from sqlalchemy import select

from ledger_service.modules.ledger.domain.entities import JournalEntry
from ledger_service.modules.ledger.infrastructure.models import (
    JournalEntryLineModel,
    JournalEntryModel,
)
from ledger_service.modules.ledger.infrastructure.repository import (
    SqlAlchemyJournalEntryRepository,
)


@pytest.mark.asyncio
async def test_create_opening_entry_persists_balanced_lines(session) -> None:
    repo = SqlAlchemyJournalEntryRepository(session)
    entry_id = await repo.create_opening_entry(
        tenant_id="tenant-a",
        entry_date=date(2026, 1, 1),
        reference="OPENING",
        description="Test",
        source_type="opening_balance",
        created_by="user-1",
        lines=[
            {
                "account_id": "acc-1",
                "debit_amount": Decimal("100"),
                "credit_amount": Decimal("0"),
                "description": "Cash",
            },
            {
                "account_id": "acc-2",
                "debit_amount": Decimal("0"),
                "credit_amount": Decimal("100"),
                "description": "Equity",
            },
        ],
    )
    result = await session.execute(
        select(JournalEntryModel).where(JournalEntryModel.id == entry_id)
    )
    header = result.scalars().one()
    assert header.source_type == "opening_balance"

    lines = await session.execute(
        select(JournalEntryLineModel).where(
            JournalEntryLineModel.journal_entry_id == entry_id
        )
    )
    assert len(lines.scalars().all()) == 2


@pytest.mark.asyncio
async def test_get_by_id_returns_entry(session) -> None:
    repo = SqlAlchemyJournalEntryRepository(session)
    entry_id = await repo.create_opening_entry(
        tenant_id="t1",
        entry_date=date(2026, 1, 1),
        reference="OPENING",
        description="Test",
        source_type="opening_balance",
        created_by=None,
        lines=[
            {"account_id": "a", "debit_amount": Decimal("5"), "credit_amount": Decimal("0")},
            {"account_id": "b", "debit_amount": Decimal("0"), "credit_amount": Decimal("5")},
        ],
    )
    found = await repo.get_by_id(entry_id)
    assert found.id == entry_id


@pytest.mark.asyncio
async def test_list_by_tenant(session) -> None:
    repo = SqlAlchemyJournalEntryRepository(session)
    await repo.create_opening_entry(
        tenant_id="list-tenant",
        entry_date=date(2026, 1, 1),
        reference="OPENING",
        description="Test",
        source_type="opening_balance",
        created_by=None,
        lines=[
            {"account_id": "a", "debit_amount": Decimal("1"), "credit_amount": Decimal("0")},
            {"account_id": "b", "debit_amount": Decimal("0"), "credit_amount": Decimal("1")},
        ],
    )
    items = await repo.list_by_tenant("list-tenant")
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_create_domain_entry(session) -> None:
    repo = SqlAlchemyJournalEntryRepository(session)
    entry = JournalEntry(
        tenant_id="t-create",
        entry_date=date(2026, 1, 2),
        reference="REF",
        description="desc",
    )
    created = await repo.create(entry)
    assert created.reference == "REF"


@pytest.mark.asyncio
async def test_get_by_id_raises_when_missing(session) -> None:
    repo = SqlAlchemyJournalEntryRepository(session)
    with pytest.raises(NotFoundError):
        await repo.get_by_id("missing-id")


@pytest.mark.asyncio
async def test_create_opening_entry_rejects_line_with_both_sides(session) -> None:
    repo = SqlAlchemyJournalEntryRepository(session)
    with pytest.raises(ValidationError, match="both debit and credit"):
        await repo.create_opening_entry(
            tenant_id="t",
            entry_date=date(2026, 1, 1),
            reference="OPENING",
            description="Test",
            source_type="opening_balance",
            created_by=None,
            lines=[
                {
                    "account_id": "a",
                    "debit_amount": Decimal("10"),
                    "credit_amount": Decimal("10"),
                },
            ],
        )


@pytest.mark.asyncio
async def test_create_opening_entry_rejects_imbalance(session) -> None:
    repo = SqlAlchemyJournalEntryRepository(session)
    with pytest.raises(ValidationError, match="must balance"):
        await repo.create_opening_entry(
            tenant_id="t",
            entry_date=date(2026, 1, 1),
            reference="OPENING",
            description="Test",
            source_type="opening_balance",
            created_by=None,
            lines=[
                {
                    "account_id": "a",
                    "debit_amount": Decimal("100"),
                    "credit_amount": Decimal("0"),
                },
                {
                    "account_id": "b",
                    "debit_amount": Decimal("0"),
                    "credit_amount": Decimal("50"),
                },
            ],
        )
