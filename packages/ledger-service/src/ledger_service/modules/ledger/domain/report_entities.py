"""Domain entities for financial reports (P&L, Balance Sheet, Cash Flow)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class ReportAccountLine:
    """A single account's aggregated balance for a report period.

    ``net_amount`` = total_debit - total_credit (raw journal line sum).
    Display sign conventions vary by report section.
    """

    account_id: str
    account_code: str
    account_name: str
    account_type: str    # "asset" | "liability" | "equity" | "revenue" | "expense"
    total_debit: Decimal = field(default_factory=Decimal)
    total_credit: Decimal = field(default_factory=Decimal)

    @property
    def net_amount(self) -> Decimal:
        """debit - credit. Asset/expense accounts normally positive; liability/equity/revenue negative."""
        return self.total_debit - self.total_credit


@dataclass(frozen=True)
class ProfitLossReport:
    """Income statement for a date range."""
    from_date: date
    to_date: date
    revenue_lines: list[ReportAccountLine]
    expense_lines: list[ReportAccountLine]
    total_revenue: Decimal
    total_expense: Decimal

    @property
    def net_profit(self) -> Decimal:
        """Revenue - Expense. Positive = profit, negative = loss."""
        return self.total_revenue - self.total_expense


@dataclass(frozen=True)
class BalanceSheetReport:
    """Statement of financial position as of a specific date."""
    as_of_date: date
    asset_lines: list[ReportAccountLine]
    liability_lines: list[ReportAccountLine]
    equity_lines: list[ReportAccountLine]
    retained_earnings: Decimal   # computed: historical Σ(revenue - expense)
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal        # COA equity + retained_earnings

    @property
    def is_balanced(self) -> bool:
        """Assets must equal Liabilities + Equity."""
        return self.total_assets == self.total_liabilities + self.total_equity

    @property
    def imbalance(self) -> Decimal:
        return self.total_assets - (self.total_liabilities + self.total_equity)


# ── Cash Flow (Phase 4 stubs — types defined for forward reference) ─────────

@dataclass(frozen=True)
class CashFlowSectionLine:
    account_id: str
    account_code: str
    account_name: str
    change_amount: Decimal   # Δ between two periods


@dataclass(frozen=True)
class CashFlowReport:
    """Statement of cash flows — indirect method."""
    from_date: date
    to_date: date
    net_income: Decimal
    operating_adjustments: list[CashFlowSectionLine]
    operating_cash_flow: Decimal
    investing_adjustments: list[CashFlowSectionLine]
    investing_cash_flow: Decimal
    financing_adjustments: list[CashFlowSectionLine]
    financing_cash_flow: Decimal
    net_cash_change: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal
