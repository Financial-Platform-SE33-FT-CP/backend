"""Unit tests for ReportService — P&L, Balance Sheet calculation logic.

Uses a mock ReportRepository with fixed data; no database needed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from ledger_service.modules.ledger.application.report_service import ReportService
from ledger_service.modules.ledger.domain.report_entities import ReportAccountLine
from ledger_service.modules.ledger.domain.report_repository import ReportRepository

# ── helpers ────────────────────────────────────────────────────────────────────

_ZERO = Decimal("0.00")

TENANT = "tenant-001"
TODAY = date(2026, 7, 15)
FY_START = date(2026, 1, 1)


def _make_line(
    account_id: str,
    code: str,
    name: str,
    account_type: str,
    total_debit: str = "0.00",
    total_credit: str = "0.00",
) -> ReportAccountLine:
    return ReportAccountLine(
        account_id=account_id,
        account_code=code,
        account_name=name,
        account_type=account_type,
        total_debit=Decimal(total_debit),
        total_credit=Decimal(total_credit),
    )


def _mock_repo(lines: list[ReportAccountLine], historical_net: Decimal = _ZERO) -> ReportRepository:
    repo = Mock(spec=ReportRepository)
    repo.get_account_summaries = AsyncMock(return_value=lines)
    repo.get_historical_net_profit = AsyncMock(return_value=historical_net)
    return repo


# ── P&L tests ──────────────────────────────────────────────────────────────────


class TestProfitLoss:
    async def test_simple_profit(self):
        """Revenue 1000 - Expense 600 = Net Profit 400."""
        lines = [
            _make_line("r1", "4000", "Sales Revenue", "revenue", "0.00", "1000.00"),
            _make_line("e1", "5000", "COGS", "expense", "400.00", "0.00"),
            _make_line("e2", "5100", "Salary", "expense", "200.00", "0.00"),
        ]
        service = ReportService(_mock_repo(lines))

        report = await service.get_profit_loss(
            tenant_id=TENANT,
            from_date=FY_START,
            to_date=TODAY,
        )

        assert report.total_revenue == Decimal("1000.00")
        assert report.total_expense == Decimal("600.00")
        assert report.net_profit == Decimal("400.00")
        assert len(report.revenue_lines) == 1
        assert len(report.expense_lines) == 2

    async def test_net_loss(self):
        """Revenue 500 - Expense 800 = Net Loss 300."""
        lines = [
            _make_line("r1", "4000", "Sales Revenue", "revenue", "0.00", "500.00"),
            _make_line("e1", "5000", "COGS", "expense", "800.00", "0.00"),
        ]
        service = ReportService(_mock_repo(lines))

        report = await service.get_profit_loss(
            tenant_id=TENANT,
            from_date=FY_START,
            to_date=TODAY,
        )

        assert report.total_revenue == Decimal("500.00")
        assert report.total_expense == Decimal("800.00")
        assert report.net_profit == Decimal("-300.00")

    async def test_zero_activity(self):
        """No revenue or expense lines → all zero."""
        lines: list[ReportAccountLine] = []
        service = ReportService(_mock_repo(lines))

        report = await service.get_profit_loss(
            tenant_id=TENANT,
            from_date=FY_START,
            to_date=TODAY,
        )

        assert report.total_revenue == _ZERO
        assert report.total_expense == _ZERO
        assert report.net_profit == _ZERO
        assert len(report.revenue_lines) == 0
        assert len(report.expense_lines) == 0

    async def test_excludes_asset_liability_equity(self):
        """Asset / Liability / Equity accounts do NOT appear in P&L."""
        lines = [
            _make_line("a1", "1000", "Cash", "asset", "5000.00", "0.00"),
            _make_line("l1", "2000", "AP", "liability", "0.00", "1000.00"),
            _make_line("e1", "3000", "Share Capital", "equity", "0.00", "4000.00"),
            _make_line("r1", "4000", "Revenue", "revenue", "0.00", "2000.00"),
            _make_line("x1", "5000", "Expense", "expense", "800.00", "0.00"),
        ]
        service = ReportService(_mock_repo(lines))

        report = await service.get_profit_loss(
            tenant_id=TENANT,
            from_date=FY_START,
            to_date=TODAY,
        )

        assert len(report.revenue_lines) == 1
        assert len(report.expense_lines) == 1
        assert report.total_revenue == Decimal("2000.00")
        assert report.total_expense == Decimal("800.00")

    async def test_date_validation(self):
        """from_date > to_date raises ValidationError."""
        service = ReportService(_mock_repo([]))

        with pytest.raises(Exception) as exc_info:  # ValidationError from shared
            await service.get_profit_loss(
                tenant_id=TENANT,
                from_date=date(2026, 12, 31),
                to_date=date(2026, 1, 1),
            )
        assert "from_date" in str(exc_info.value).lower()

    async def test_sorted_by_code(self):
        """Account lines are sorted by account_code."""
        lines = [
            _make_line("r2", "4200", "Other Income", "revenue", "0.00", "300.00"),
            _make_line("r1", "4000", "Sales", "revenue", "0.00", "700.00"),
            _make_line("e2", "5200", "Rent", "expense", "100.00", "0.00"),
            _make_line("e1", "5000", "COGS", "expense", "200.00", "0.00"),
        ]
        service = ReportService(_mock_repo(lines))

        report = await service.get_profit_loss(
            tenant_id=TENANT,
            from_date=FY_START,
            to_date=TODAY,
        )

        codes_r = [ln.account_code for ln in report.revenue_lines]
        codes_e = [ln.account_code for ln in report.expense_lines]
        assert codes_r == ["4000", "4200"]
        assert codes_e == ["5000", "5200"]


# ── Balance Sheet tests ────────────────────────────────────────────────────────


class TestBalanceSheet:
    async def test_simple_balance(self):
        """Assets 5000 = Liabilities 1000 + Equity(1000) + RE(3000)."""
        lines = [
            _make_line("a1", "1000", "Cash", "asset", "5000.00", "0.00"),
            _make_line("l1", "2000", "AP", "liability", "0.00", "1000.00"),
            _make_line("e1", "3000", "Share Capital", "equity", "0.00", "1000.00"),
        ]
        historical = Decimal("3000.00")  # retained earnings
        service = ReportService(_mock_repo(lines, historical))

        report = await service.get_balance_sheet(
            tenant_id=TENANT,
            as_of_date=TODAY,
        )

        assert report.total_assets == Decimal("5000.00")
        assert report.total_liabilities == Decimal("1000.00")
        assert report.total_equity == Decimal("4000.00")  # 1000 + 3000
        assert report.retained_earnings == Decimal("3000.00")
        assert report.is_balanced is True
        assert report.imbalance == _ZERO

    async def test_negative_retained_earnings(self):
        """Accumulated losses reduce equity."""
        lines = [
            _make_line("a1", "1000", "Cash", "asset", "1000.00", "0.00"),
            _make_line("e1", "3000", "Share Capital", "equity", "0.00", "2000.00"),
        ]
        historical = Decimal("-500.00")  # accumulated loss
        service = ReportService(_mock_repo(lines, historical))

        report = await service.get_balance_sheet(
            tenant_id=TENANT,
            as_of_date=TODAY,
        )

        assert report.total_equity == Decimal("1500.00")  # 2000 + (-500)
        assert report.retained_earnings == Decimal("-500.00")
        # A=1000, L=0, E=1500 → not balanced (test data is deliberately imbalanced)
        assert report.is_balanced is False
        assert report.imbalance == Decimal("-500.00")

    async def test_imbalanced_detection(self):
        """When Assets != Liabilities + Equity, imbalance is reported."""
        lines = [
            _make_line("a1", "1000", "Cash", "asset", "5000.00", "0.00"),
            _make_line("l1", "2000", "AP", "liability", "0.00", "2000.00"),
            _make_line("e1", "3000", "Share Capital", "equity", "0.00", "1000.00"),
        ]
        historical = Decimal("0.00")  # RE = 0, so A=5000, L+E=3000, imbalance=2000
        service = ReportService(_mock_repo(lines, historical))

        report = await service.get_balance_sheet(
            tenant_id=TENANT,
            as_of_date=TODAY,
        )

        assert report.is_balanced is False
        assert report.imbalance == Decimal("2000.00")

    async def test_empty_balance_sheet(self):
        """No data → all zeros, balanced."""
        service = ReportService(_mock_repo([], _ZERO))

        report = await service.get_balance_sheet(
            tenant_id=TENANT,
            as_of_date=TODAY,
        )

        assert report.total_assets == _ZERO
        assert report.total_liabilities == _ZERO
        assert report.total_equity == _ZERO
        assert report.is_balanced is True

    async def test_sorted_sections(self):
        """Each section sorted by account_code."""
        lines = [
            _make_line("a2", "1500", "Fixed Assets", "asset", "2000.00", "0.00"),
            _make_line("a1", "1000", "Cash", "asset", "3000.00", "0.00"),
            _make_line("l2", "2100", "GST Output", "liability", "0.00", "300.00"),
            _make_line("l1", "2000", "AP", "liability", "0.00", "700.00"),
            _make_line("e2", "3100", "Retained Earnings", "equity", "0.00", "1000.00"),
            _make_line("e1", "3000", "Share Capital", "equity", "0.00", "3000.00"),
        ]
        service = ReportService(_mock_repo(lines, _ZERO))

        report = await service.get_balance_sheet(
            tenant_id=TENANT,
            as_of_date=TODAY,
        )

        assert [ln.account_code for ln in report.asset_lines] == ["1000", "1500"]
        assert [ln.account_code for ln in report.liability_lines] == ["2000", "2100"]
        assert [ln.account_code for ln in report.equity_lines] == ["3000", "3100"]


# ── Edge cases shared across reports ───────────────────────────────────────────


class TestEdgeCases:
    async def test_contra_revenue_ignored(self):
        """Revenue account with net debit balance is excluded (display=0)."""
        lines = [
            _make_line("r1", "4000", "Sales Revenue", "revenue", "0.00", "1000.00"),
            _make_line("r2", "4100", "Sales Returns", "revenue", "200.00", "0.00"),
            # r2 has net_amount = 200 - 0 = 200 (debit), _to_display_amount → 0
        ]
        service = ReportService(_mock_repo(lines))

        report = await service.get_profit_loss(
            tenant_id=TENANT,
            from_date=FY_START,
            to_date=TODAY,
        )

        assert report.total_revenue == Decimal("1000.00")
        # Sales Returns (net debit) is excluded because display = 0
        assert len(report.revenue_lines) == 1
