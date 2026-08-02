"""Report application service — P&L, Balance Sheet, Cash Flow.

Design decisions (see epic9-findings.md):
- Reports read from ``monthly_account_balances`` (materialized) once Phase 2
  populates it; until then the repository bridges to ``journal_entry_lines``.
- Retained Earnings is computed on-the-fly (report-layer injection, plan A).
  When US-20 (year-end close) is implemented, migrate to a real COA account.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from accounting_shared.exceptions import ValidationError

from ledger_service.modules.ledger.domain.report_entities import (
    BalanceSheetReport,
    CashFlowReport,
    CashFlowSectionLine,
    ProfitLossReport,
    ReportAccountLine,
)
from ledger_service.modules.ledger.domain.report_repository import ReportRepository
from ledger_service.modules.ledger.infrastructure.cash_flow_mapping import (
    CFSection,
    get_cf_section,
)

_ZERO = Decimal("0.00")

# ── helpers ────────────────────────────────────────────────────────────────────


def _to_display_amount(account_type: str, net_amount: Decimal) -> Decimal:
    """Normalise an account balance to its natural display sign.

    * asset / expense → normally debit  → positive display
    * liability / equity / revenue → normally credit → positive display

    Returns a non-negative Decimal representing the absolute balance
    on the *normal* side of the account.
    """
    if account_type in ("asset", "expense"):
        # debit-side normal balance
        return max(net_amount, _ZERO)
    # liability, equity, revenue — credit-side normal balance
    return max(-net_amount, _ZERO)


# ── service ────────────────────────────────────────────────────────────────────


class ReportService:
    """Compute P&L, Balance Sheet and Cash Flow from ledger aggregates."""

    def __init__(self, repo: ReportRepository) -> None:
        self._repo = repo

    # ── P&L ─────────────────────────────────────────────────────────────────

    async def get_profit_loss(
        self,
        *,
        tenant_id: str,
        from_date: date | None,
        to_date: date,
    ) -> ProfitLossReport:
        if from_date is not None and from_date > to_date:
            raise ValidationError("from_date cannot be after to_date.")

        lines = await self._repo.get_account_summaries(
            tenant_id=tenant_id,
            from_date=from_date,
            to_date=to_date,
        )

        revenue_lines: list[ReportAccountLine] = []
        expense_lines: list[ReportAccountLine] = []
        total_revenue = _ZERO
        total_expense = _ZERO

        for line in lines:
            display = _to_display_amount(line.account_type, line.net_amount)
            if display == _ZERO:
                continue

            if line.account_type == "revenue":
                revenue_lines.append(line)
                total_revenue += display
            elif line.account_type == "expense":
                expense_lines.append(line)
                total_expense += display
            # asset / liability / equity accounts are excluded from P&L

        revenue_lines.sort(key=lambda ln: ln.account_code)
        expense_lines.sort(key=lambda ln: ln.account_code)

        return ProfitLossReport(
            from_date=from_date or date.min,
            to_date=to_date,
            revenue_lines=revenue_lines,
            expense_lines=expense_lines,
            total_revenue=total_revenue,
            total_expense=total_expense,
        )

    # ── Cash Flow ───────────────────────────────────────────────────────────

    async def get_cash_flow(
        self,
        *,
        tenant_id: str,
        from_date: date,
        to_date: date,
    ) -> CashFlowReport:
        if from_date > to_date:
            raise ValidationError("from_date cannot be after to_date.")

        # Net income for the period
        pnl = await self.get_profit_loss(
            tenant_id=tenant_id, from_date=from_date, to_date=to_date,
        )

        # Balance sheets at start and end of period
        bs_end = await self.get_balance_sheet(
            tenant_id=tenant_id, as_of_date=to_date,
        )
        bs_start = await self.get_balance_sheet(
            tenant_id=tenant_id, as_of_date=from_date,
        )

        # Compute per-account changes from start → end
        # Build lookup: account_id → start_net_amount
        start_by_id: dict[str, Decimal] = {}
        for lines in [bs_start.asset_lines, bs_start.liability_lines, bs_start.equity_lines]:
            for ln in lines:
                start_by_id[ln.account_id] = ln.net_amount

        end_by_id: dict[str, Decimal] = {}
        for lines in [bs_end.asset_lines, bs_end.liability_lines, bs_end.equity_lines]:
            for ln in lines:
                end_by_id[ln.account_id] = ln.net_amount

        # Classify changes by CF section
        operating_adjustments: list[CashFlowSectionLine] = []
        investing_adjustments: list[CashFlowSectionLine] = []
        financing_adjustments: list[CashFlowSectionLine] = []
        beginning_cash = _ZERO
        ending_cash = _ZERO

        all_account_ids = set(start_by_id.keys()) | set(end_by_id.keys())
        for account_id in all_account_ids:
            end_net = end_by_id.get(account_id, _ZERO)
            start_net = start_by_id.get(account_id, _ZERO)

            # Find account info from end BS
            account: ReportAccountLine | None = None
            for lines in [
                bs_end.asset_lines,
                bs_end.liability_lines,
                bs_end.equity_lines,
            ]:
                for ln in lines:
                    if ln.account_id == account_id:
                        account = ln
                        break
                if account:
                    break
            if account is None:
                # Fall back to start BS
                for lines in [
                    bs_start.asset_lines,
                    bs_start.liability_lines,
                    bs_start.equity_lines,
                ]:
                    for ln in lines:
                        if ln.account_id == account_id:
                            account = ln
                            break
                    if account:
                        break
            if account is None:
                continue

            section = get_cf_section(account.account_code)
            if section is None:
                continue

            # change = end_net - start_net
            # For asset accounts (debit normal): increase = cash OUTFLOW → negative
            # For liability/equity (credit normal): increase = cash INFLOW → positive
            # Operating assets: increase → cash used  → -change (or -(Δ) as cash_impact)
            # Operating liabilities: increase → cash source → +change
            change = end_net - start_net

            if change == _ZERO:
                continue

            if section == CFSection.CASH:
                beginning_cash = start_net
                ending_cash = end_net
                continue   # cash itself is the reconciliation target, not an adjustment

            # Cash flow impact: for assets (debit normal), negative change = cash inflow
            # for liabilities/equity (credit normal), positive change = cash inflow
            if section in (
                CFSection.OPERATING_ASSET,
                CFSection.INVESTING_ASSET,
            ):
                cash_impact = -change   # asset increase = cash used
            else:
                cash_impact = change    # liability/equity increase = cash source

            line = CashFlowSectionLine(
                account_id=account.account_id,
                account_code=account.account_code,
                account_name=account.account_name,
                change_amount=cash_impact,
            )

            if section == CFSection.OPERATING_ASSET or section == CFSection.OPERATING_LIABILITY:
                operating_adjustments.append(line)
            elif section == CFSection.INVESTING_ASSET:
                investing_adjustments.append(line)
            elif section in (CFSection.FINANCING_LIABILITY, CFSection.EQUITY):
                financing_adjustments.append(line)

        # Non-cash expense add-backs are not yet classified in the COA.
        # Future: map account_code → CFSection.NON_CASH_EXPENSE and add Depreciation etc.

        operating_cf = pnl.net_profit + sum(
            ln.change_amount for ln in operating_adjustments
        )
        investing_cf = sum(ln.change_amount for ln in investing_adjustments)
        financing_cf = sum(ln.change_amount for ln in financing_adjustments)
        net_cash_change = operating_cf + investing_cf + financing_cf

        operating_adjustments.sort(key=lambda ln: ln.account_code)
        investing_adjustments.sort(key=lambda ln: ln.account_code)
        financing_adjustments.sort(key=lambda ln: ln.account_code)

        return CashFlowReport(
            from_date=from_date,
            to_date=to_date,
            net_income=pnl.net_profit,
            operating_adjustments=operating_adjustments,
            operating_cash_flow=operating_cf,
            investing_adjustments=investing_adjustments,
            investing_cash_flow=investing_cf,
            financing_adjustments=financing_adjustments,
            financing_cash_flow=financing_cf,
            net_cash_change=net_cash_change,
            beginning_cash=beginning_cash,
            ending_cash=ending_cash,
        )

    # ── Balance Sheet ───────────────────────────────────────────────────────

    async def get_balance_sheet(
        self,
        *,
        tenant_id: str,
        as_of_date: date,
    ) -> BalanceSheetReport:
        # All journal activity through as_of_date
        lines = await self._repo.get_account_summaries(
            tenant_id=tenant_id,
            from_date=None,     # from the beginning
            to_date=as_of_date,
        )

        asset_lines: list[ReportAccountLine] = []
        liability_lines: list[ReportAccountLine] = []
        equity_lines: list[ReportAccountLine] = []
        total_assets = _ZERO
        total_liabilities = _ZERO
        total_coa_equity = _ZERO

        for line in lines:
            display = _to_display_amount(line.account_type, line.net_amount)
            if display == _ZERO:
                continue

            if line.account_type == "asset":
                asset_lines.append(line)
                total_assets += display
            elif line.account_type == "liability":
                liability_lines.append(line)
                total_liabilities += display
            elif line.account_type == "equity":
                equity_lines.append(line)
                total_coa_equity += display
            # revenue / expense excluded — they are captured via retained earnings

        # Retained earnings = historical cumulative net profit
        retained_earnings = await self._repo.get_historical_net_profit(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
        )
        total_equity = total_coa_equity + retained_earnings

        asset_lines.sort(key=lambda ln: ln.account_code)
        liability_lines.sort(key=lambda ln: ln.account_code)
        equity_lines.sort(key=lambda ln: ln.account_code)

        return BalanceSheetReport(
            as_of_date=as_of_date,
            asset_lines=asset_lines,
            liability_lines=liability_lines,
            equity_lines=equity_lines,
            retained_earnings=retained_earnings,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            total_equity=total_equity,
        )
