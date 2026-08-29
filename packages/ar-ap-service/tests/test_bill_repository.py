from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from ar_ap_service.modules.ar_ap.domain.entities import Bill, BillLine
from ar_ap_service.modules.ar_ap.infrastructure.models import BillLineModel
from ar_ap_service.modules.ar_ap.infrastructure.repository import SqlAlchemyBillRepository

GST_CODE_ID = UUID("43c58cb7-cae2-4a9f-9794-693034ffb3da")


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    def __init__(self, existing_model: object | None = None) -> None:
        self.added: list[object] = []
        self.existing_model = existing_model
        self.execute_count = 0

    def add(self, model: object) -> None:
        self.added.append(model)

    async def flush(self) -> None:
        return None

    async def execute(self, _statement: object) -> _ScalarResult:
        self.execute_count += 1

        if self.execute_count == 1 and self.existing_model is not None:
            return _ScalarResult(self.existing_model)

        return _ScalarResult(None)

    async def get(
        self,
        _model_type: object,
        _model_id: object,
    ) -> object | None:
        return self.existing_model


def _build_bill() -> Bill:
    line = BillLine(
        account_id=uuid4(),
        quantity=Decimal("1"),
        unit_price=Decimal("500"),
        description="Marketing Materials",
        gst_code_id=GST_CODE_ID,
        gst_rate=Decimal("0.09"),
    )
    line.recalculate()

    bill = Bill(
        tenant_id=uuid4(),
        vendor_id=uuid4(),
        issue_date=date(2026, 8, 8),
        due_date=date(2026, 9, 7),
        lines=[line],
    )
    bill.recalculate_totals()

    return bill


def _find_persisted_bill_lines(
    session: _FakeSession,
    extra_container: object | None = None,
) -> list[BillLineModel]:
    found = [model for model in session.added if isinstance(model, BillLineModel)]

    for model in session.added:
        lines = getattr(model, "lines", [])
        found.extend(line for line in lines if isinstance(line, BillLineModel))

    if extra_container is not None:
        lines = getattr(extra_container, "lines", [])
        found.extend(line for line in lines if isinstance(line, BillLineModel))

    return found


@pytest.mark.asyncio
async def test_bill_repository_add_preserves_gst_code_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bill = _build_bill()
    session = _FakeSession()
    repository = SqlAlchemyBillRepository(session)  # type: ignore[arg-type]

    reloaded = AsyncMock(return_value=bill)

    monkeypatch.setattr(repository, "get_by_id", reloaded)
    monkeypatch.setattr(
        repository,
        "_reload",
        reloaded,
        raising=False,
    )

    await repository.add(bill)

    persisted_lines = _find_persisted_bill_lines(session)

    assert len(persisted_lines) == 1
    assert persisted_lines[0].gst_code_id == GST_CODE_ID
    assert persisted_lines[0].gst_rate == Decimal("0.09")
    assert persisted_lines[0].gst_amount == Decimal("45.00")


@pytest.mark.asyncio
async def test_bill_repository_update_preserves_gst_code_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bill = _build_bill()

    existing_model = SimpleNamespace(lines=[])

    session = _FakeSession(existing_model=existing_model)
    repository = SqlAlchemyBillRepository(session)  # type: ignore[arg-type]

    reloaded = AsyncMock(return_value=bill)

    monkeypatch.setattr(repository, "get_by_id", reloaded)
    monkeypatch.setattr(
        repository,
        "_reload",
        reloaded,
        raising=False,
    )

    await repository.update(bill)

    persisted_lines = _find_persisted_bill_lines(
        session,
        existing_model,
    )

    assert len(persisted_lines) == 1
    assert persisted_lines[0].gst_code_id == GST_CODE_ID
    assert persisted_lines[0].gst_rate == Decimal("0.09")
    assert persisted_lines[0].gst_amount == Decimal("45.00")
