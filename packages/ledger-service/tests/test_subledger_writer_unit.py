from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from ledger_service.modules.opening_balance.domain.entities import ApAgingLine, ArAgingLine
from ledger_service.modules.opening_balance.infrastructure.subledger_writer import (
    OpeningSubledgerWriter,
)


@pytest.mark.asyncio
async def test_create_ar_aging_adds_invoice() -> None:
    session = AsyncMock()
    customer_result = MagicMock()
    customer_result.scalars.return_value.first.return_value = None
    session.execute.return_value = customer_result
    session.flush = AsyncMock()

    writer = OpeningSubledgerWriter(session)
    count = await writer.create_ar_aging(
        tenant_id=str(uuid.uuid4()),
        journal_entry_id="je-1",
        lines=[
            ArAgingLine(
                2,
                "Acme",
                Decimal("10.00"),
                date(2026, 1, 15),
                "OPEN-1",
            )
        ],
        revenue_account_id=str(uuid.uuid4()),
    )
    assert count == 1
    assert session.add.called


@pytest.mark.asyncio
async def test_create_ar_aging_reuses_existing_customer() -> None:
    session = AsyncMock()
    existing = MagicMock()
    existing.id = uuid.uuid4()
    customer_result = MagicMock()
    customer_result.scalars.return_value.first.return_value = existing
    session.execute.return_value = customer_result
    session.flush = AsyncMock()

    writer = OpeningSubledgerWriter(session)
    count = await writer.create_ar_aging(
        tenant_id=str(uuid.uuid4()),
        journal_entry_id="je-1",
        lines=[
            ArAgingLine(2, "Acme", Decimal("5"), date(2026, 1, 1), "R"),
        ],
        revenue_account_id=str(uuid.uuid4()),
    )
    assert count == 1


@pytest.mark.asyncio
async def test_create_ap_aging_adds_bill() -> None:
    session = AsyncMock()
    vendor_result = MagicMock()
    vendor_result.scalars.return_value.first.return_value = None
    session.execute.return_value = vendor_result
    session.flush = AsyncMock()

    writer = OpeningSubledgerWriter(session)
    count = await writer.create_ap_aging(
        tenant_id=str(uuid.uuid4()),
        journal_entry_id="je-1",
        lines=[
            ApAgingLine(
                2,
                "Vendor",
                Decimal("20.00"),
                date(2026, 2, 1),
                "OPEN-AP",
            )
        ],
        expense_account_id=str(uuid.uuid4()),
    )
    assert count == 1
