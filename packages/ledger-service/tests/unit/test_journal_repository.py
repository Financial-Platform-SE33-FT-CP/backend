from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.exceptions import ValidationError
from coa_service.modules.coa.infrastructure.models import AccountModel
from ledger_service.modules.ledger.domain.entities import JournalEntry, JournalEntryLine
from ledger_service.modules.ledger.infrastructure.models import (
    JournalEntryLineModel,
    JournalEntryModel,
)
from ledger_service.modules.ledger.infrastructure.repository import (
    SqlAlchemyJournalEntryRepository,
)

TENANT_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_entry(**kwargs):
    defaults = {
        "tenant_id": TENANT_ID,
        "entry_date": date.today(),
        "reference": "JE-U",
        "description": "unit test",
        "source_type": "manual",
        "created_by": "test",
    }
    defaults.update(kwargs)
    return JournalEntry(**defaults)


def _make_line(**kwargs):
    defaults = {
        "tenant_id": TENANT_ID,
        "account_id": "10000000-0000-0000-0000-000000000001",
        "debit_amount": Decimal("100"),
        "credit_amount": Decimal("0"),
        "description": "line",
    }
    defaults.update(kwargs)
    return JournalEntryLine(**defaults)


# ============================================================================
# create
# ============================================================================


@pytest.mark.asyncio
async def test_create_persists_entry_and_lines(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)

    entry = _make_entry()
    line1 = _make_line(journal_entry_id=entry.id, account_id="aa000000-0000-0000-0000-000000000001", debit_amount=Decimal("100"), credit_amount=Decimal("0"))
    line2 = _make_line(journal_entry_id=entry.id, account_id="bb000000-0000-0000-0000-000000000001", debit_amount=Decimal("0"), credit_amount=Decimal("100"))
    entry.lines = [line1, line2]

    created = await repo.create(entry)

    # verify returned entity
    assert created.id == entry.id
    assert len(created.lines) == 2

    # verify database state
    stmt = select(JournalEntryModel).where(JournalEntryModel.id == entry.id)
    result = await session.execute(stmt)
    model = result.scalar_one()
    assert model.reference == "JE-U"
    assert model.source_type == "manual"

    lines_stmt = select(JournalEntryLineModel).where(
        JournalEntryLineModel.journal_entry_id == entry.id
    )
    lines_result = await session.execute(lines_stmt)
    lines = lines_result.scalars().all()
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_create_assigns_reversal_flags(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)
    entry = _make_entry(is_reversal=True, reversed_entry_id="reversed-uuid")
    entry.lines = [
        _make_line(journal_entry_id=entry.id, debit_amount=Decimal("50"), credit_amount=Decimal("0")),
        _make_line(journal_entry_id=entry.id, account_id="bb000000-0000-0000-0000-000000000001", debit_amount=Decimal("0"), credit_amount=Decimal("50")),
    ]

    created = await repo.create(entry)
    assert created.is_reversal is True
    assert created.reversed_entry_id == "reversed-uuid"


# ============================================================================
# get_by_id
# ============================================================================


@pytest.mark.asyncio
async def test_get_by_id_returns_entry_with_lines(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)

    entry = _make_entry()
    entry.lines = [
        _make_line(journal_entry_id=entry.id, debit_amount=Decimal("100"), credit_amount=Decimal("0")),
        _make_line(journal_entry_id=entry.id, account_id="bb000000-0000-0000-0000-000000000001", debit_amount=Decimal("0"), credit_amount=Decimal("100")),
    ]
    await repo.create(entry)

    fetched = await repo.get_by_id(TENANT_ID, entry.id)
    assert fetched is not None
    assert fetched.id == entry.id
    assert fetched.reference == "JE-U"
    assert len(fetched.lines) == 2
    assert fetched.lines[0].debit_amount == Decimal("100")


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_wrong_tenant(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)
    entry = _make_entry()
    entry.lines = [_make_line(journal_entry_id=entry.id), _make_line(journal_entry_id=entry.id, debit_amount=Decimal("0"), credit_amount=Decimal("100"), account_id="bb000000-0000-0000-0000-000000000001")]
    await repo.create(entry)

    fetched = await repo.get_by_id("99999999-0000-0000-0000-000000000009", entry.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)
    fetched = await repo.get_by_id(TENANT_ID, "nonexistent-uuid")
    assert fetched is None


# ============================================================================
# list_by_tenant
# ============================================================================


@pytest.mark.asyncio
async def test_list_by_tenant_pagination(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)

    for i in range(5):
        entry = _make_entry(reference=f"JE-{i}")
        entry.lines = [
            _make_line(journal_entry_id=entry.id, debit_amount=Decimal("10"), credit_amount=Decimal("0")),
            _make_line(journal_entry_id=entry.id, account_id="bb000000-0000-0000-0000-000000000001", debit_amount=Decimal("0"), credit_amount=Decimal("10")),
        ]
        await repo.create(entry)

    # first page
    page1 = await repo.list_by_tenant(TENANT_ID, offset=0, limit=2)
    assert len(page1) == 2

    # second page
    page2 = await repo.list_by_tenant(TENANT_ID, offset=2, limit=2)
    assert len(page2) == 2

    # no overlap
    ids_page1 = {e.id for e in page1}
    ids_page2 = {e.id for e in page2}
    assert ids_page1.isdisjoint(ids_page2)


@pytest.mark.asyncio
async def test_list_by_tenant_empty(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)
    entries = await repo.list_by_tenant(TENANT_ID)
    assert entries == []


# ============================================================================
# get_account_balance_before
# ============================================================================


@pytest.mark.asyncio
async def test_get_account_balance_before_sums_correctly(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)

    # create entries on different dates
    entry1 = _make_entry(entry_date=date(2026, 1, 10))
    entry1.lines = [
        _make_line(journal_entry_id=entry1.id, debit_amount=Decimal("100"), credit_amount=Decimal("0")),
        _make_line(journal_entry_id=entry1.id, account_id="bb000000-0000-0000-0000-000000000001", debit_amount=Decimal("0"), credit_amount=Decimal("100")),
    ]
    await repo.create(entry1)

    entry2 = _make_entry(entry_date=date(2026, 1, 20))
    entry2.lines = [
        _make_line(journal_entry_id=entry2.id, debit_amount=Decimal("30"), credit_amount=Decimal("0")),
        _make_line(journal_entry_id=entry2.id, account_id="bb000000-0000-0000-0000-000000000001", debit_amount=Decimal("0"), credit_amount=Decimal("30")),
    ]
    await repo.create(entry2)

    # balance before Jan 15 should only include entry1 (debit: 100)
    balance = await repo.get_account_balance_before(
        tenant_id=TENANT_ID,
        account_id="10000000-0000-0000-0000-000000000001",
        before_date=date(2026, 1, 15),
    )
    assert balance == Decimal("100.00")

    # balance before Jan 25 should include both (debit: 130)
    balance = await repo.get_account_balance_before(
        tenant_id=TENANT_ID,
        account_id="10000000-0000-0000-0000-000000000001",
        before_date=date(2026, 1, 25),
    )
    assert balance == Decimal("130.00")


@pytest.mark.asyncio
async def test_get_account_balance_before_returns_zero_when_empty(session: AsyncSession):
    repo = SqlAlchemyJournalEntryRepository(session)
    balance = await repo.get_account_balance_before(
        tenant_id=TENANT_ID,
        account_id="unused-account",
        before_date=date(2026, 1, 1),
    )
    assert balance == Decimal("0.00")
