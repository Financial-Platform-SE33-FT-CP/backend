from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from accounting_shared.exceptions import ValidationError

from ledger_service.modules.opening_balance.application.csv_parser import (
    parse_opening_balance_csv,
)
from ledger_service.modules.opening_balance.application.opening_balance_service import (
    OpeningBalanceService,
)
from ledger_service.modules.opening_balance.domain.entities import (
    ParsedOpeningImport,
    TrialBalanceLine,
)


def _balanced_csv() -> str:
    return (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1000,100.00,0,,,,,\n"
        "trial_balance,3200,0,100.00,,,,,\n"
    )


@pytest.mark.asyncio
async def test_has_opening_balance_false_when_empty(session) -> None:
    service = OpeningBalanceService(session)
    assert await service.has_opening_balance("tenant-x") is False


@pytest.mark.asyncio
async def test_validate_import_returns_errors_for_unknown_codes(session) -> None:
    service = OpeningBalanceService(session)
    parsed = parse_opening_balance_csv(_balanced_csv())
    with patch.object(
        service._coa,
        "resolve_codes",
        new_callable=AsyncMock,
        return_value={},
    ):
        result, issues = await service.validate_import(
            "00000000-0000-0000-0000-000000000099", parsed
        )
    assert result["valid"] is False
    assert issues


@pytest.mark.asyncio
async def test_validate_import_ok_when_resolved(session) -> None:
    service = OpeningBalanceService(session)
    parsed = parse_opening_balance_csv(_balanced_csv())
    with patch.object(
        service._coa,
        "resolve_codes",
        new_callable=AsyncMock,
        return_value={"1000": "a1", "3200": "a2"},
    ):
        result, issues = await service.validate_import(
            "00000000-0000-0000-0000-000000000001", parsed
        )
    assert result["valid"] is True
    assert issues == []


@pytest.mark.asyncio
async def test_import_opening_balance_success(session) -> None:
    service = OpeningBalanceService(session)
    parsed = parse_opening_balance_csv(_balanced_csv())

    with (
        patch.object(
            service,
            "has_opening_balance",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch.object(
            service._coa,
            "resolve_codes",
            new_callable=AsyncMock,
            return_value={"1000": "a1", "3200": "a2"},
        ),
        patch.object(
            service._journal_repo,
            "create_opening_entry",
            new_callable=AsyncMock,
            return_value="je-1",
        ) as create_je,
        patch.object(
            service._subledger,
            "create_ar_aging",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch.object(
            service._subledger,
            "create_ap_aging",
            new_callable=AsyncMock,
            return_value=0,
        ),
    ):
        tenant = "00000000-0000-0000-0000-000000000001"
        result = await service.import_opening_balance(
            tenant_id=tenant,
            parsed=parsed,
            entry_date=date(2026, 1, 1),
            created_by="user-1",
        )

    assert result["journal_entry_id"] == "je-1"
    assert result["line_count"] == 2
    create_je.assert_awaited_once()

    with (
        patch.object(
            service, "has_opening_balance", new_callable=AsyncMock, return_value=True
        ),
        patch.object(
            service._coa,
            "resolve_codes",
            new_callable=AsyncMock,
            return_value={"1000": "a1", "3200": "a2"},
        ),
    ):
        with pytest.raises(ValidationError, match="already been imported"):
            await service.import_opening_balance(
                tenant_id=tenant,
                parsed=parsed,
                entry_date=date(2026, 1, 1),
                created_by=None,
            )


@pytest.mark.asyncio
async def test_import_with_ar_ap_aging(session) -> None:
    service = OpeningBalanceService(session)
    csv_text = (
        "section,account_code,debit,credit,counterparty_name,amount,due_date,reference,description\n"
        "trial_balance,1100,50.00,0,,,,,\n"
        "trial_balance,2000,0,30.00,,,,,\n"
        "trial_balance,3200,0,20.00,,,,,\n"
        "ar_aging,,,,Acme Pte,50.00,2026-01-15,OPEN-AR-001,\n"
        "ap_aging,,,,Vendor,30.00,2026-02-01,OPEN-AP-001,\n"
    )
    parsed = service.parse_csv(csv_text)

    with (
        patch.object(
            service, "has_opening_balance", new_callable=AsyncMock, return_value=False
        ),
        patch.object(
            service._coa,
            "resolve_codes",
            new_callable=AsyncMock,
            return_value={
                "1100": "ar",
                "2000": "ap",
                "3200": "eq",
                "4000": "rev",
                "6900": "exp",
            },
        ),
        patch.object(
            service._journal_repo,
            "create_opening_entry",
            new_callable=AsyncMock,
            return_value="je-2",
        ),
        patch.object(
            service._subledger,
            "create_ar_aging",
            new_callable=AsyncMock,
            return_value=1,
        ) as ar_create,
        patch.object(
            service._subledger,
            "create_ap_aging",
            new_callable=AsyncMock,
            return_value=1,
        ) as ap_create,
    ):
        result = await service.import_opening_balance(
            tenant_id="tenant-1",
            parsed=parsed,
            entry_date=date(2026, 1, 1),
            created_by=None,
        )

    assert result["ar_documents_created"] == 1
    assert result["ap_documents_created"] == 1
    ar_create.assert_awaited_once()
    ap_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_requires_revenue_account_for_ar(session) -> None:
    from ledger_service.modules.opening_balance.domain.entities import ArAgingLine

    service = OpeningBalanceService(session)
    parsed = ParsedOpeningImport(
        trial_balance=[
            TrialBalanceLine(2, "1100", Decimal("10"), Decimal("0")),
            TrialBalanceLine(3, "3200", Decimal("0"), Decimal("10")),
        ],
        ar_aging=[ArAgingLine(4, "C", Decimal("10"), date(2026, 1, 1), "R1")],
    )

    with (
        patch.object(
            service, "has_opening_balance", new_callable=AsyncMock, return_value=False
        ),
        patch.object(
            service._coa,
            "resolve_codes",
            new_callable=AsyncMock,
            return_value={"1100": "ar", "3200": "eq"},
        ),
        patch.object(
            service._journal_repo,
            "create_opening_entry",
            new_callable=AsyncMock,
            return_value="je-3",
        ),
    ):
        with pytest.raises(ValidationError, match="4000"):
            await service.import_opening_balance(
                tenant_id="t",
                parsed=parsed,
                entry_date=date(2026, 1, 1),
                created_by=None,
            )


def test_parse_csv_delegates() -> None:
    service = OpeningBalanceService(MagicMock())
    parsed = service.parse_csv(_balanced_csv())
    assert len(parsed.trial_balance) == 2
