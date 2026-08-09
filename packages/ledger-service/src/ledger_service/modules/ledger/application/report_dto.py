"""Pydantic DTOs for financial report responses."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ReportAccountLineDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_code: str
    account_name: str
    account_type: str  # "asset" | "liability" | "equity" | "revenue" | "expense"
    total_debit: Decimal
    total_credit: Decimal
    net_amount: Decimal  # debit - credit


class ProfitLossReportDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_date: date
    to_date: date
    revenue_lines: list[ReportAccountLineDTO]
    expense_lines: list[ReportAccountLineDTO]
    total_revenue: Decimal
    total_expense: Decimal
    net_profit: Decimal


class BalanceSheetReportDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    asset_lines: list[ReportAccountLineDTO]
    liability_lines: list[ReportAccountLineDTO]
    equity_lines: list[ReportAccountLineDTO]
    retained_earnings: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    is_balanced: bool
    imbalance: Decimal


# ── Cash Flow ──────────────────────────────────────────────────────────────────


class CashFlowSectionLineDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_code: str
    account_name: str
    change_amount: Decimal  # Δ between two periods (positive = cash inflow)


class CashFlowReportDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_date: date
    to_date: date
    net_income: Decimal
    operating_adjustments: list[CashFlowSectionLineDTO]
    operating_cash_flow: Decimal
    investing_adjustments: list[CashFlowSectionLineDTO]
    investing_cash_flow: Decimal
    financing_adjustments: list[CashFlowSectionLineDTO]
    financing_cash_flow: Decimal
    net_cash_change: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal
