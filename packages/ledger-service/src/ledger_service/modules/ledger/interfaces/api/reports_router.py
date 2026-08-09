"""Financial report API endpoints — P&L, Balance Sheet, Cash Flow."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from accounting_shared.rbac import P_ACCOUNTING_READ
from accounting_shared.types import TenantId
from ledger_service.deps import (
    RequireLedgerPermission,
    get_report_service,
    require_tenant_id,
)
from ledger_service.modules.ledger.application.report_service import ReportService
from ledger_service.modules.ledger.interfaces.api.report_schemas import (
    BalanceSheetResponse,
    CashFlowResponse,
    ProfitLossResponse,
)

router = APIRouter(tags=["reports"])


def _line_to_response(line) -> dict:
    return {
        "account_id": line.account_id,
        "account_code": line.account_code,
        "account_name": line.account_name,
        "account_type": line.account_type,
        "total_debit": line.total_debit,
        "total_credit": line.total_credit,
        "net_amount": line.net_amount,
    }


@router.get("/profit-loss", response_model=ProfitLossResponse)
async def get_profit_loss(
    _: Annotated[None, Depends(RequireLedgerPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[ReportService, Depends(get_report_service)],
    from_date: date | None = Query(
        None, description="Period start (inclusive). None = earliest entry."
    ),
    to_date: date = Query(..., description="Period end (inclusive)."),
) -> ProfitLossResponse:
    report = await service.get_profit_loss(
        tenant_id=str(tenant_id),
        from_date=from_date,
        to_date=to_date,
    )
    return ProfitLossResponse(
        from_date=report.from_date,
        to_date=report.to_date,
        revenue_lines=[_line_to_response(ln) for ln in report.revenue_lines],
        expense_lines=[_line_to_response(ln) for ln in report.expense_lines],
        total_revenue=report.total_revenue,
        total_expense=report.total_expense,
        net_profit=report.net_profit,
    )


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
async def get_balance_sheet(
    _: Annotated[None, Depends(RequireLedgerPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[ReportService, Depends(get_report_service)],
    as_of_date: date = Query(..., description="Balance sheet date."),
) -> BalanceSheetResponse:
    report = await service.get_balance_sheet(
        tenant_id=str(tenant_id),
        as_of_date=as_of_date,
    )
    return BalanceSheetResponse(
        as_of_date=report.as_of_date,
        asset_lines=[_line_to_response(ln) for ln in report.asset_lines],
        liability_lines=[_line_to_response(ln) for ln in report.liability_lines],
        equity_lines=[_line_to_response(ln) for ln in report.equity_lines],
        retained_earnings=report.retained_earnings,
        total_assets=report.total_assets,
        total_liabilities=report.total_liabilities,
        total_equity=report.total_equity,
        is_balanced=report.is_balanced,
        imbalance=report.imbalance,
    )


@router.get("/cash-flow", response_model=CashFlowResponse)
async def get_cash_flow(
    _: Annotated[None, Depends(RequireLedgerPermission(P_ACCOUNTING_READ))],
    tenant_id: Annotated[TenantId, Depends(require_tenant_id)],
    service: Annotated[ReportService, Depends(get_report_service)],
    from_date: date = Query(..., description="Period start (inclusive)."),
    to_date: date = Query(..., description="Period end (inclusive)."),
) -> CashFlowResponse:
    report = await service.get_cash_flow(
        tenant_id=str(tenant_id),
        from_date=from_date,
        to_date=to_date,
    )
    return CashFlowResponse(
        from_date=report.from_date,
        to_date=report.to_date,
        net_income=report.net_income,
        operating_adjustments=[
            {
                "account_id": ln.account_id,
                "account_code": ln.account_code,
                "account_name": ln.account_name,
                "change_amount": ln.change_amount,
            }
            for ln in report.operating_adjustments
        ],
        operating_cash_flow=report.operating_cash_flow,
        investing_adjustments=[
            {
                "account_id": ln.account_id,
                "account_code": ln.account_code,
                "account_name": ln.account_name,
                "change_amount": ln.change_amount,
            }
            for ln in report.investing_adjustments
        ],
        investing_cash_flow=report.investing_cash_flow,
        financing_adjustments=[
            {
                "account_id": ln.account_id,
                "account_code": ln.account_code,
                "account_name": ln.account_name,
                "change_amount": ln.change_amount,
            }
            for ln in report.financing_adjustments
        ],
        financing_cash_flow=report.financing_cash_flow,
        net_cash_change=report.net_cash_change,
        beginning_cash=report.beginning_cash,
        ending_cash=report.ending_cash,
    )
