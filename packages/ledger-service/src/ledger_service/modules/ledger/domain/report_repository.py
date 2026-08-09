"""Repository interfaces for financial reports."""

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from ledger_service.modules.ledger.domain.report_entities import ReportAccountLine


class ReportRepository(ABC):
    """Read-side repository for financial report aggregation.

    Implementations may query ``journal_entry_lines`` directly or use
    the ``monthly_account_balances`` materialized view.
    """

    @abstractmethod
    async def get_account_summaries(
        self,
        *,
        tenant_id: str,
        from_date: date | None,
        to_date: date,
    ) -> list[ReportAccountLine]:
        """Return per-account debit/credit totals for a date range.

        ``from_date`` may be None → from the first journal entry.
        Accounts with zero total debit AND credit are omitted.
        """

    @abstractmethod
    async def get_historical_net_profit(
        self,
        *,
        tenant_id: str,
        as_of_date: date,
    ) -> Decimal:
        """Return Σ(revenue) - Σ(expense) from day one through ``as_of_date``.

        Used as Retained Earnings in the Balance Sheet.
        """
