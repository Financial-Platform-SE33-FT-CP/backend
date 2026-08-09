"""Pydantic request/response schemas for financial report endpoints."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# ── shared line ────────────────────────────────────────────────────────────────


class ReportAccountLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_code: str
    account_name: str
    account_type: str
    total_debit: Decimal
    total_credit: Decimal
    net_amount: Decimal


# ── P&L ────────────────────────────────────────────────────────────────────────


class ProfitLossResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_date: date
    to_date: date
    revenue_lines: list[ReportAccountLineResponse]
    expense_lines: list[ReportAccountLineResponse]
    total_revenue: Decimal
    total_expense: Decimal
    net_profit: Decimal


# ── Balance Sheet ──────────────────────────────────────────────────────────────


class BalanceSheetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    asset_lines: list[ReportAccountLineResponse]
    liability_lines: list[ReportAccountLineResponse]
    equity_lines: list[ReportAccountLineResponse]
    retained_earnings: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    is_balanced: bool
    imbalance: Decimal


# ── Cash Flow ──────────────────────────────────────────────────────────────────


class CashFlowSectionLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_code: str
    account_name: str
    change_amount: Decimal


class CashFlowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_date: date
    to_date: date
    net_income: Decimal
    operating_adjustments: list[CashFlowSectionLineResponse]
    operating_cash_flow: Decimal
    investing_adjustments: list[CashFlowSectionLineResponse]
    investing_cash_flow: Decimal
    financing_adjustments: list[CashFlowSectionLineResponse]
    financing_cash_flow: Decimal
    net_cash_change: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal
