"""Integration tests for EPIC 9 — P&L, Balance Sheet, Cash Flow.

Uses the ``session`` fixture (SQLite in-memory) with seeded COA + journal data.
Tests ReportRepository and ReportService against known ledger entries.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from coa_service.modules.coa.infrastructure.models import AccountModel, AccountType
from ledger_service.modules.ledger.application.report_service import ReportService
from ledger_service.modules.ledger.domain.report_entities import (
    ProfitLossReport,
    BalanceSheetReport,
    CashFlowReport,
)
from ledger_service.modules.ledger.infrastructure.models import (
    JournalEntryLineModel,
    JournalEntryModel,
)
from ledger_service.modules.ledger.infrastructure.report_repository import (
    SqlAlchemyReportRepository,
)

Z = Decimal("0.00")

# ── helpers ────────────────────────────────────────────────────────────────────


async def _seed_account(
    session,
    *,
    tid: uuid.UUID,
    aid: uuid.UUID,
    code: str,
    name: str,
    atype: AccountType,
) -> None:
    now = datetime.utcnow()
    session.add(
        AccountModel(
            id=aid,
            tenant_id=tid,
            code=code,
            name=name,
            account_type=atype,
            parent_id=None,
            is_active=True,
            is_system_default=False,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()


async def _seed_journal(
    session,
    *,
    tid: str,
    eid: str,
    entry_date: date,
    reference: str,
    lines: list[tuple[str, str, str]],
) -> None:
    """Create a journal entry with lines. Each line is (account_id, debit, credit)."""
    now = datetime.utcnow()
    session.add(
        JournalEntryModel(
            id=eid,
            tenant_id=tid,
            entry_date=entry_date,
            reference=reference,
            description="",
            source_type="manual",
            created_by="test",
            created_at=now,
        )
    )
    for account_id, debit, credit in lines:
        session.add(
            JournalEntryLineModel(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                journal_entry_id=eid,
                account_id=account_id,
                debit_amount=Decimal(debit),
                credit_amount=Decimal(credit),
            )
        )
    await session.flush()


# ── fixture: seeded tenant ─────────────────────────────────────────────────────


@pytest.fixture
async def seeded(session):
    """Seed a tenant with 7 accounts and 3 journal entries covering a full cycle.

    Scenario (one month, July 2026):
        JE-1: Dr Cash 5000, Cr Share Capital 5000    (initial investment)
        JE-2: Dr Cash 3000, Cr Sales Revenue 3000     (earned revenue)
        JE-3: Dr COGS 1200, Cr Cash 1200              (paid expense)

    NOTE: monthly_account_balances is not created here — the session fixture
    doesn't set it up, and ReportRepository queries journal_entry_lines directly.
    """
    tid = uuid.uuid4()
    tid_str = str(tid)

    # ── accounts ──
    cash_id = uuid.uuid4()
    ar_id = uuid.uuid4()
    ap_id = uuid.uuid4()
    share_cap_id = uuid.uuid4()
    sales_id = uuid.uuid4()
    cogs_id = uuid.uuid4()
    rent_id = uuid.uuid4()

    await _seed_account(session, tid=tid, aid=cash_id, code="1000", name="Cash", atype=AccountType.ASSET)
    await _seed_account(session, tid=tid, aid=ar_id, code="1100", name="Accounts Receivable", atype=AccountType.ASSET)
    await _seed_account(session, tid=tid, aid=ap_id, code="2000", name="Accounts Payable", atype=AccountType.LIABILITY)
    await _seed_account(session, tid=tid, aid=share_cap_id, code="3000", name="Share Capital", atype=AccountType.EQUITY)
    await _seed_account(session, tid=tid, aid=sales_id, code="4000", name="Sales Revenue", atype=AccountType.REVENUE)
    await _seed_account(session, tid=tid, aid=cogs_id, code="5000", name="COGS", atype=AccountType.EXPENSE)
    await _seed_account(session, tid=tid, aid=rent_id, code="6000", name="Rent Expense", atype=AccountType.EXPENSE)

    # ── journal entries ──
    await _seed_journal(session, tid=tid_str, eid=str(uuid.uuid4()), entry_date=date(2026, 7, 1),
                        reference="JE-1", lines=[
                            (str(cash_id), "5000.00", "0.00"),
                            (str(share_cap_id), "0.00", "5000.00"),
                        ])
    await _seed_journal(session, tid=tid_str, eid=str(uuid.uuid4()), entry_date=date(2026, 7, 10),
                        reference="JE-2", lines=[
                            (str(cash_id), "3000.00", "0.00"),
                            (str(sales_id), "0.00", "3000.00"),
                        ])
    await _seed_journal(session, tid=tid_str, eid=str(uuid.uuid4()), entry_date=date(2026, 7, 20),
                        reference="JE-3", lines=[
                            (str(cogs_id), "1200.00", "0.00"),
                            (str(cash_id), "0.00", "1200.00"),
                        ])

    return {
        "tid": tid_str,
        "accounts": {
            "cash": str(cash_id),
            "ar": str(ar_id),
            "ap": str(ap_id),
            "share_cap": str(share_cap_id),
            "sales": str(sales_id),
            "cogs": str(cogs_id),
            "rent": str(rent_id),
        },
    }


# ── P&L integration tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profit_loss_calculates_correctly(session, seeded) -> None:
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    pl = await svc.get_profit_loss(
        tenant_id=seeded["tid"],
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
    )

    assert isinstance(pl, ProfitLossReport)
    assert pl.total_revenue == Decimal("3000.00")   # JE-2: Sales 3000
    assert pl.total_expense == Decimal("1200.00")    # JE-3: COGS 1200
    assert pl.net_profit == Decimal("1800.00")       # 3000 - 1200
    assert len(pl.revenue_lines) == 1
    assert len(pl.expense_lines) == 1
    assert pl.revenue_lines[0].account_code == "4000"
    assert pl.expense_lines[0].account_code == "5000"


@pytest.mark.asyncio
async def test_profit_loss_excludes_bs_accounts(session, seeded) -> None:
    """P&L must not include asset/liability/equity account lines."""
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    pl = await svc.get_profit_loss(
        tenant_id=seeded["tid"],
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
    )

    all_codes = {ln.account_code for ln in pl.revenue_lines + pl.expense_lines}
    assert "1000" not in all_codes   # Cash
    assert "3000" not in all_codes   # Share Capital


@pytest.mark.asyncio
async def test_profit_loss_with_date_range(session, seeded) -> None:
    """Only entries within the date range are counted."""
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    # Only JE-2 and JE-3 fall in this range
    pl = await svc.get_profit_loss(
        tenant_id=seeded["tid"],
        from_date=date(2026, 7, 5),
        to_date=date(2026, 7, 25),
    )

    assert pl.total_revenue == Decimal("3000.00")   # JE-2: 2026-07-10
    assert pl.total_expense == Decimal("1200.00")    # JE-3: 2026-07-20


# ── Balance Sheet integration tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_balance_sheet_balances(session, seeded) -> None:
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    bs = await svc.get_balance_sheet(
        tenant_id=seeded["tid"],
        as_of_date=date(2026, 7, 31),
    )

    assert isinstance(bs, BalanceSheetReport)
    # Cash: 5000 + 3000 - 1200 = 6800
    assert bs.total_assets == Decimal("6800.00")
    assert bs.total_liabilities == Z
    # Equity: Share Capital 5000 + RE 1800 = 6800
    assert bs.total_equity == Decimal("6800.00")
    assert bs.retained_earnings == Decimal("1800.00")
    assert bs.is_balanced is True
    assert bs.imbalance == Z
    assert bs.total_assets == bs.total_liabilities + bs.total_equity


@pytest.mark.asyncio
async def test_balance_sheet_retained_earnings_equals_cumulative_pl(session, seeded) -> None:
    """BS retained_earnings must equal cumulative P&L from day 1."""
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    bs = await svc.get_balance_sheet(tenant_id=seeded["tid"], as_of_date=date(2026, 7, 31))
    pl = await svc.get_profit_loss(tenant_id=seeded["tid"], from_date=None, to_date=date(2026, 7, 31))

    assert bs.retained_earnings == pl.net_profit


# ── Cash Flow integration tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cash_flow_reconciles(session, seeded) -> None:
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    cf = await svc.get_cash_flow(
        tenant_id=seeded["tid"],
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
    )

    assert isinstance(cf, CashFlowReport)
    assert cf.net_income == Decimal("1800.00")   # from P&L
    # Net income 1800, no operating adjustments → operating CF = 1800
    assert cf.operating_cash_flow == Decimal("1800.00")
    # Cash: JE-1=5000 + JE-2=3000 - JE-3=1200 = 6800 end
    assert cf.ending_cash == Decimal("6800.00")
    # JE-1 on from_date (2026-07-01) → included in beginning BS
    assert cf.beginning_cash == Decimal("5000.00")
    # net_cash_change = operating(1800) right? But ending(6800)-beginning(5000)=1800
    assert cf.net_cash_change == cf.ending_cash - cf.beginning_cash


# ── Repository-level tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repository_account_summaries_respect_dates(session, seeded) -> None:
    repo = SqlAlchemyReportRepository(session)

    # July 1 only
    lines = await repo.get_account_summaries(
        tenant_id=seeded["tid"],
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 1),
    )
    codes = {ln.account_code for ln in lines}
    assert codes == {"1000", "3000"}   # JE-1 only


@pytest.mark.asyncio
async def test_repository_historical_net_profit(session, seeded) -> None:
    repo = SqlAlchemyReportRepository(session)

    np_mid = await repo.get_historical_net_profit(
        tenant_id=seeded["tid"], as_of_date=date(2026, 7, 15),
    )
    np_end = await repo.get_historical_net_profit(
        tenant_id=seeded["tid"], as_of_date=date(2026, 7, 31),
    )

    assert np_mid == Decimal("3000.00")   # JE-2 only (revenue), JE-3 not yet
    assert np_end == Decimal("1800.00")   # all entries


# ── Invariant tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invariant_balance_sheet_always_balances(session, seeded) -> None:
    """No matter the date, Assets must equal Liabilities + Equity."""
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    for d in [date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 31)]:
        bs = await svc.get_balance_sheet(tenant_id=seeded["tid"], as_of_date=d)
        assert bs.is_balanced, f"BS not balanced at {d}: imbalance={bs.imbalance}"
        assert bs.total_assets == bs.total_liabilities + bs.total_equity, \
            f"A={bs.total_assets} != L+E={bs.total_liabilities + bs.total_equity} at {d}"


@pytest.mark.asyncio
async def test_invariant_pl_net_profit_equals_retained_earnings_delta(session, seeded) -> None:
    """Net profit between two dates = Δ retained earnings between those dates."""
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    # Period: July 5-25
    pl = await svc.get_profit_loss(
        tenant_id=seeded["tid"],
        from_date=date(2026, 7, 5),
        to_date=date(2026, 7, 25),
    )
    bs_start = await svc.get_balance_sheet(tenant_id=seeded["tid"], as_of_date=date(2026, 7, 4))
    bs_end = await svc.get_balance_sheet(tenant_id=seeded["tid"], as_of_date=date(2026, 7, 25))

    re_delta = bs_end.retained_earnings - bs_start.retained_earnings
    assert pl.net_profit == re_delta, \
        f"P&L net={pl.net_profit} != RE delta={re_delta}"


@pytest.mark.asyncio
async def test_invariant_empty_data_all_zeros(session) -> None:
    """Empty tenant → all reports return zeros, BS is balanced."""
    tid = str(uuid.uuid4())
    # No accounts, no journal entries
    repo = SqlAlchemyReportRepository(session)
    svc = ReportService(repo)

    pl = await svc.get_profit_loss(tenant_id=tid, from_date=None, to_date=date(2026, 7, 31))
    bs = await svc.get_balance_sheet(tenant_id=tid, as_of_date=date(2026, 7, 31))

    assert pl.total_revenue == Z
    assert pl.total_expense == Z
    assert pl.net_profit == Z
    assert bs.total_assets == Z
    assert bs.is_balanced is True
