from __future__ import annotations

from decimal import Decimal

import pytest

from ledger_service.modules.opening_balance.application.validator import (
    OpeningBalanceValidator,
)
from ledger_service.modules.opening_balance.domain.entities import (
    ApAgingLine,
    ArAgingLine,
    ParsedOpeningImport,
    TrialBalanceLine,
)


class FakeCoaResolver:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def resolve_codes(self, tenant_id: str, codes: set[str]) -> dict[str, str]:
        return {c: self._mapping[c] for c in codes if c in self._mapping}


@pytest.mark.asyncio
async def test_validate_balanced_import_ok() -> None:
    parsed = ParsedOpeningImport(
        trial_balance=[
            TrialBalanceLine(2, "1100", Decimal("50"), Decimal("0")),
            TrialBalanceLine(3, "3200", Decimal("0"), Decimal("50")),
        ],
        ar_aging=[
            ArAgingLine(4, "Acme", Decimal("50"), __import__("datetime").date(2026, 1, 15), "R1"),
        ],
    )
    resolver = FakeCoaResolver({"1100": "a1", "3200": "a2"})
    validator = OpeningBalanceValidator(resolver)
    preview, lines, issues = await validator.validate("tenant-1", parsed)
    assert not issues
    assert preview.total_debit == Decimal("50")
    assert len(lines) == 2


@pytest.mark.asyncio
async def test_validate_reports_unknown_account() -> None:
    parsed = ParsedOpeningImport(
        trial_balance=[TrialBalanceLine(2, "9999", Decimal("10"), Decimal("0"))],
    )
    validator = OpeningBalanceValidator(FakeCoaResolver({}))
    _, _, issues = await validator.validate("t1", parsed)
    assert any(i.field == "account_code" for i in issues)


@pytest.mark.asyncio
async def test_validate_reports_imbalance() -> None:
    parsed = ParsedOpeningImport(
        trial_balance=[
            TrialBalanceLine(2, "1000", Decimal("100"), Decimal("0")),
            TrialBalanceLine(3, "3200", Decimal("0"), Decimal("50")),
        ],
    )
    validator = OpeningBalanceValidator(
        FakeCoaResolver({"1000": "a", "3200": "b"})
    )
    _, _, issues = await validator.validate("t1", parsed)
    assert any(i.field == "trial_balance" for i in issues)


@pytest.mark.asyncio
async def test_validate_ar_total_mismatch() -> None:
    parsed = ParsedOpeningImport(
        trial_balance=[
            TrialBalanceLine(2, "1100", Decimal("100"), Decimal("0")),
            TrialBalanceLine(3, "3200", Decimal("0"), Decimal("100")),
        ],
        ar_aging=[
            ArAgingLine(4, "X", Decimal("40"), __import__("datetime").date(2026, 1, 1), "R"),
        ],
    )
    validator = OpeningBalanceValidator(
        FakeCoaResolver({"1100": "a", "3200": "b"})
    )
    _, _, issues = await validator.validate("t1", parsed)
    assert any(i.field == "ar_aging" for i in issues)


@pytest.mark.asyncio
async def test_validate_ap_total_mismatch() -> None:
    parsed = ParsedOpeningImport(
        trial_balance=[
            TrialBalanceLine(2, "2000", Decimal("0"), Decimal("80")),
            TrialBalanceLine(3, "3200", Decimal("0"), Decimal("80")),
        ],
        ap_aging=[
            ApAgingLine(4, "V", Decimal("50"), __import__("datetime").date(2026, 1, 1), "B1"),
        ],
    )
    validator = OpeningBalanceValidator(
        FakeCoaResolver({"2000": "a", "3200": "b"})
    )
    _, _, issues = await validator.validate("t1", parsed)
    assert any(i.field == "ap_aging" for i in issues)


@pytest.mark.asyncio
async def test_validate_opening_already_posted() -> None:
    parsed = ParsedOpeningImport(
        trial_balance=[
            TrialBalanceLine(2, "1000", Decimal("10"), Decimal("0")),
            TrialBalanceLine(3, "3200", Decimal("0"), Decimal("10")),
        ],
    )
    validator = OpeningBalanceValidator(FakeCoaResolver({"1000": "a", "3200": "b"}))
    _, _, issues = await validator.validate("t1", parsed, opening_already_posted=True)
    assert any(i.field == "tenant" for i in issues)


@pytest.mark.asyncio
async def test_validate_duplicate_ar_reference() -> None:
    d = __import__("datetime").date(2026, 1, 1)
    parsed = ParsedOpeningImport(
        trial_balance=[
            TrialBalanceLine(2, "1100", Decimal("20"), Decimal("0")),
            TrialBalanceLine(3, "3200", Decimal("0"), Decimal("20")),
        ],
        ar_aging=[
            ArAgingLine(4, "A", Decimal("10"), d, "DUP"),
            ArAgingLine(5, "B", Decimal("10"), d, "DUP"),
        ],
    )
    validator = OpeningBalanceValidator(
        FakeCoaResolver({"1100": "a", "3200": "b"})
    )
    _, _, issues = await validator.validate("t1", parsed)
    assert any(i.field == "reference" for i in issues)
