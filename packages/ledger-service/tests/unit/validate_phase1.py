"""Quick validation of Phase 1 code — runs in container without pytest."""
from decimal import Decimal
from datetime import date
from unittest.mock import AsyncMock, Mock

from ledger_service.modules.ledger.domain.report_entities import ReportAccountLine
from ledger_service.modules.ledger.application.report_service import ReportService, _to_display_amount

_Z = Decimal("0.00")
TODAY = date(2026, 7, 15)
FY = date(2026, 1, 1)


def L(aid, code, name, atype, dr="0.00", cr="0.00"):
    return ReportAccountLine(
        account_id=aid, account_code=code, account_name=name,
        account_type=atype, total_debit=Decimal(dr), total_credit=Decimal(cr),
    )


async def main():
    repo = Mock()
    repo.get_account_summaries = AsyncMock()
    repo.get_historical_net_profit = AsyncMock(return_value=_Z)
    svc = ReportService(repo)
    passed = 0
    failed = 0

    # 1. P&L simple profit
    repo.get_account_summaries.return_value = [
        L("r1", "4000", "Revenue", "revenue", "0.00", "1000.00"),
        L("e1", "5000", "COGS", "expense", "400.00", "0.00"),
        L("e2", "5100", "Salary", "expense", "200.00", "0.00"),
    ]
    r = await svc.get_profit_loss(tenant_id="t1", from_date=FY, to_date=TODAY)
    assert r.total_revenue == Decimal("1000.00"), f"revenue: {r.total_revenue}"
    assert r.total_expense == Decimal("600.00"), f"expense: {r.total_expense}"
    assert r.net_profit == Decimal("400.00"), f"net: {r.net_profit}"
    passed += 1; print("[PASS] 1. P&L simple profit")

    # 2. P&L net loss
    repo.get_account_summaries.return_value = [
        L("r1", "4000", "Sales", "revenue", "0.00", "500.00"),
        L("e1", "5000", "COGS", "expense", "800.00", "0.00"),
    ]
    r = await svc.get_profit_loss(tenant_id="t1", from_date=FY, to_date=TODAY)
    assert r.net_profit == Decimal("-300.00"), f"net: {r.net_profit}"
    passed += 1; print("[PASS] 2. P&L net loss")

    # 3. P&L zero activity
    repo.get_account_summaries.return_value = []
    r = await svc.get_profit_loss(tenant_id="t1", from_date=FY, to_date=TODAY)
    assert r.total_revenue == _Z and r.total_expense == _Z and r.net_profit == _Z
    passed += 1; print("[PASS] 3. P&L zero activity")

    # 4. Excludes asset/liability/equity from P&L
    repo.get_account_summaries.return_value = [
        L("a1", "1000", "Cash", "asset", "5000.00", "0.00"),
        L("l1", "2000", "AP", "liability", "0.00", "1000.00"),
        L("e1", "3000", "Capital", "equity", "0.00", "4000.00"),
        L("r1", "4000", "Revenue", "revenue", "0.00", "2000.00"),
        L("x1", "5000", "Expense", "expense", "800.00", "0.00"),
    ]
    r = await svc.get_profit_loss(tenant_id="t1", from_date=FY, to_date=TODAY)
    assert len(r.revenue_lines) == 1 and len(r.expense_lines) == 1
    passed += 1; print("[PASS] 4. Excludes BS accounts from P&L")

    # 5. BS simple balance
    repo.get_account_summaries.return_value = [
        L("a1", "1000", "Cash", "asset", "5000.00", "0.00"),
        L("l1", "2000", "AP", "liability", "0.00", "1000.00"),
        L("e1", "3000", "Capital", "equity", "0.00", "1000.00"),
    ]
    repo.get_historical_net_profit.return_value = Decimal("3000.00")
    r = await svc.get_balance_sheet(tenant_id="t1", as_of_date=TODAY)
    assert r.total_assets == Decimal("5000.00"), f"assets: {r.total_assets}"
    assert r.total_liabilities == Decimal("1000.00"), f"liab: {r.total_liabilities}"
    assert r.total_equity == Decimal("4000.00"), f"equity: {r.total_equity}"
    assert r.retained_earnings == Decimal("3000.00"), f"RE: {r.retained_earnings}"
    assert r.is_balanced is True, f"imbalance: {r.imbalance}"
    passed += 1; print("[PASS] 5. BS simple balance")

    # 6. BS imbalance
    repo.get_account_summaries.return_value = [
        L("a1", "1000", "Cash", "asset", "5000.00", "0.00"),
        L("l1", "2000", "AP", "liability", "0.00", "2000.00"),
        L("e1", "3000", "Capital", "equity", "0.00", "1000.00"),
    ]
    repo.get_historical_net_profit.return_value = _Z
    r = await svc.get_balance_sheet(tenant_id="t1", as_of_date=TODAY)
    assert r.is_balanced is False, "should be imbalanced"
    assert r.imbalance == Decimal("2000.00"), f"imbalance: {r.imbalance}"
    passed += 1; print("[PASS] 6. BS imbalance detection")

    # 7. Contra revenue excluded
    repo.get_account_summaries.return_value = [
        L("r1", "4000", "Sales", "revenue", "0.00", "1000.00"),
        L("r2", "4100", "Returns", "revenue", "200.00", "0.00"),
    ]
    r = await svc.get_profit_loss(tenant_id="t1", from_date=FY, to_date=TODAY)
    assert r.total_revenue == Decimal("1000.00"), f"revenue: {r.total_revenue}"
    assert len(r.revenue_lines) == 1, f"lines: {len(r.revenue_lines)}"
    passed += 1; print("[PASS] 7. Contra revenue excluded")

    # 8. Date validation
    try:
        await svc.get_profit_loss(tenant_id="t1", from_date=date(2026, 12, 31), to_date=date(2026, 1, 1))
        print("[FAIL] 8. Should have raised")
        failed += 1
    except Exception as e:
        if "from_date" in str(e).lower():
            passed += 1; print("[PASS] 8. Date validation")
        else:
            failed += 1; print(f"[FAIL] 8. Wrong error: {e}")

    # 9. Negative retained earnings
    repo.get_account_summaries.return_value = [
        L("a1", "1000", "Cash", "asset", "1000.00", "0.00"),
        L("e1", "3000", "Capital", "equity", "0.00", "2000.00"),
    ]
    repo.get_historical_net_profit.return_value = Decimal("-500.00")
    r = await svc.get_balance_sheet(tenant_id="t1", as_of_date=TODAY)
    assert r.total_equity == Decimal("1500.00"), f"equity: {r.total_equity}"
    assert r.retained_earnings == Decimal("-500.00"), f"RE: {r.retained_earnings}"
    passed += 1; print("[PASS] 9. Negative RE reduces equity")

    # 10. Sorted by code
    repo.get_account_summaries.return_value = [
        L("x2", "5200", "Rent", "expense", "100.00", "0.00"),
        L("x1", "5000", "COGS", "expense", "200.00", "0.00"),
    ]
    r = await svc.get_profit_loss(tenant_id="t1", from_date=FY, to_date=TODAY)
    assert [ln.account_code for ln in r.expense_lines] == ["5000", "5200"], \
        f"order: {[ln.account_code for ln in r.expense_lines]}"
    passed += 1; print("[PASS] 10. Sorted by code")

    # 11. _to_display_amount helper
    assert _to_display_amount("asset", Decimal("100")) == Decimal("100")
    assert _to_display_amount("asset", Decimal("-50")) == Decimal("0")
    assert _to_display_amount("liability", Decimal("-100")) == Decimal("100")
    assert _to_display_amount("liability", Decimal("50")) == Decimal("0")
    assert _to_display_amount("revenue", Decimal("-1000")) == Decimal("1000")
    assert _to_display_amount("expense", Decimal("500")) == Decimal("500")
    passed += 1; print("[PASS] 11. _to_display_amount")

    print(f"\n=== {passed}/{passed+failed} tests passed ===")
    if failed > 0:
        raise SystemExit(1)

import asyncio
asyncio.run(main())
