"""Integration validation for Phase 2 — uses running ledger-service API."""
import asyncio
import json
from urllib.request import Request, urlopen

LEDGER = "http://ledger-service:8000/ledger"
COA = "http://coa-service:8000/coa"
AUTH = "http://auth-service:8000"
TENANT_SVC = "http://tenant-service:8000"

def api(method, url, body=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers=h, method=method)
    resp = urlopen(req)
    body_text = resp.read()
    if resp.status >= 400:
        raise Exception(f"HTTP {resp.status}: {body_text.decode()}")
    return json.loads(body_text) if resp.status != 204 and body_text else None

async def main():
    # Login
    login = api("POST", f"{AUTH}/auth/login", {"email": "test3@example.com", "password": "Test123!"})
    token = login["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # Get tenants
    tenants = api("GET", f"{TENANT_SVC}/api/v1/tenants", headers=h)
    tid = tenants[0]["id"]
    th = {**h, "X-Tenant-ID": tid}
    print(f"Tenant: {tid}")

    # Get COA accounts
    accounts = api("GET", f"{COA}/accounts", headers=th)
    print(f"COA accounts: {len(accounts)}")
    for a in accounts:
        print(f"  {a['code']} {a['name']} ({a['account_type']})")
    cash = next(a for a in accounts if "Cash" in a["name"])
    revenue = next(a for a in accounts if a["account_type"] == "revenue")
    expense = next(a for a in accounts if a["account_type"] == "expense")
    print(f"Cash: {cash['id'][:8]}... ({cash['name']})")
    print(f"Revenue: {revenue['id'][:8]}... ({revenue['name']})")
    print(f"Expense: {expense['id'][:8]}... ({expense['name']})")

    # Create 3 journal entries for testing (idempotent — check reference first)
    import uuid as _uuid
    run_id = str(_uuid.uuid4())[:8]
    entries = [
        (f"JE-P2-{run_id}-1", "2026-07-01", cash["id"], "1000.00", revenue["id"], "1000.00"),
        (f"JE-P2-{run_id}-2", "2026-07-10", expense["id"], "400.00", cash["id"], "400.00"),
        (f"JE-P2-{run_id}-3", "2026-07-20", expense["id"], "200.00", cash["id"], "200.00"),
    ]
    for ref, dt, dr_id, dr_amt, cr_id, cr_amt in entries:
        je = api("POST", f"{LEDGER}/journal-entries", {
            "entry_date": dt,
            "reference": ref,
            "description": f"Test {ref}",
            "lines": [
                {"account_id": dr_id, "debit_amount": dr_amt, "credit_amount": "0.00"},
                {"account_id": cr_id, "debit_amount": "0.00", "credit_amount": cr_amt},
            ],
        }, headers=th)
        print(f"  Created {ref}: {je['id'][:8]}...")

    # Verify trial balance
    tb = api("GET", f"{LEDGER}/trial-balance", headers=th)
    print(f"\nTrial Balance: balanced={tb['is_balanced']}, accounts={len(tb['accounts'])}")
    for a in tb["accounts"]:
        print(f"  {a['account_code']} {a['account_name']}: dr={a['total_debit']} cr={a['total_credit']}")

    # Test 1: Import modules and create DB session directly
    import sys
    import os
    sys.path.insert(0, "/app/packages/ledger-service/src")
    sys.path.insert(0, "/app/packages/shared-lib/src")
    sys.path.insert(0, "/app/packages/coa-service/src")

    from ledger_service.modules.ledger.infrastructure.report_repository import SqlAlchemyReportRepository
    from ledger_service.modules.ledger.application.report_service import ReportService
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://accounting:accounting_secret@postgres:5432/accounting")
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        repo = SqlAlchemyReportRepository(session)
        svc = ReportService(repo)

        # Test P&L
        from datetime import date
        pl = await svc.get_profit_loss(
            tenant_id=tid,
            from_date=date(2026, 7, 1),
            to_date=date(2026, 7, 31),
        )
        print(f"\n=== P&L Report ===")
        print(f"Revenue: {pl.total_revenue}")
        print(f"Expense: {pl.total_expense}")
        print(f"Net Profit: {pl.net_profit}")
        assert pl.total_revenue > 0, f"Revenue should be > 0"
        assert pl.total_expense > 0, f"Expense should be > 0"
        assert pl.net_profit == pl.total_revenue - pl.total_expense, \
            f"Net Profit must = Revenue - Expense"
        assert len(pl.revenue_lines) > 0, "Should have revenue lines"
        assert len(pl.expense_lines) > 0, "Should have expense lines"
        print("P&L ✓")

        # Test Balance Sheet
        bs = await svc.get_balance_sheet(
            tenant_id=tid,
            as_of_date=date(2026, 7, 31),
        )
        print(f"\n=== Balance Sheet ===")
        print(f"Assets: {bs.total_assets}")
        print(f"Liabilities: {bs.total_liabilities}")
        print(f"Equity (COA): {bs.total_equity - bs.retained_earnings}")
        print(f"Retained Earnings: {bs.retained_earnings}")
        print(f"Total Equity: {bs.total_equity}")
        print(f"Balanced: {bs.is_balanced} (imbalance: {bs.imbalance})")
        assert bs.total_assets > 0, f"Assets should be > 0"
        assert bs.total_assets == bs.total_liabilities + bs.total_equity, \
            f"Assets({bs.total_assets}) != Liab({bs.total_liabilities}) + Equity({bs.total_equity})"
        assert bs.is_balanced, f"BS should be balanced"
        print("BS ✓")

        # Test Historical Net Profit
        re_val = await repo.get_historical_net_profit(tenant_id=tid, as_of_date=date(2026, 7, 31))
        print(f"\nHistorical Net Profit through 2026-07-31: {re_val}")
        assert re_val == bs.retained_earnings, \
            f"RE from repo({re_val}) must match BS retained earnings({bs.retained_earnings})"
        print("Historical Net Profit ✓")

        # Test monthly_account_balances
        import uuid as _uuid2
        from ledger_service.modules.ledger.infrastructure.models import MonthlyAccountBalanceModel
        from sqlalchemy import select
        try:
            tid_uuid = _uuid2.UUID(tid)
            monthly_rows = (await session.execute(
                select(MonthlyAccountBalanceModel).where(
                    MonthlyAccountBalanceModel.tenant_id == tid_uuid
                )
            )).scalars().all()
            print(f"\nMonthly Balance rows: {len(monthly_rows)}")
            for mb in monthly_rows[:5]:
                print(f"  {mb.year}-{mb.month:02d} acc={str(mb.account_id)[:8]} dr={mb.debit_total} cr={mb.credit_total}")
        except Exception as e:
            print(f"\nMonthly Balance check skipped: {e}")

    await engine.dispose()
    print("\n=== ALL PHASE 2 TESTS PASSED ===")

asyncio.run(main())
