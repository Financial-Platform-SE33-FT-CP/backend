"""SqlAlchemy implementation of :class:`ReportRepository`.

Queries ``journal_entry_lines`` (will read from ``monthly_account_balances``
once the upsert in ``SqlAlchemyJournalEntryRepository`` is fully populated).

Sign conventions:
    * net_amount = SUM(debit) - SUM(credit)
    * asset / expense  → normally debit  (net positive)
    * liability / equity / revenue → normally credit (net negative)
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import true as sa_true
from sqlalchemy.ext.asyncio import AsyncSession

from coa_service.modules.coa.infrastructure.models import AccountModel, AccountType
from ledger_service.modules.ledger.domain.report_entities import ReportAccountLine
from ledger_service.modules.ledger.domain.report_repository import ReportRepository
from ledger_service.modules.ledger.infrastructure.models import (
    JournalEntryLineModel,
    JournalEntryModel,
)


class SqlAlchemyReportRepository(ReportRepository):
    """Aggregates report data from ``journal_entry_lines`` with COA enrichment."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if value is None:
            return Decimal("0.00")
        return Decimal(str(value))

    @staticmethod
    def _to_tenant_uuid(tenant_id: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(tenant_id)
        except ValueError:
            return None

    # ── account summaries ──────────────────────────────────────────────────

    async def get_account_summaries(
        self,
        *,
        tenant_id: str,
        from_date: date | None,
        to_date: date,
    ) -> list[ReportAccountLine]:
        tenant_uuid = self._to_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return []

        # Step 1: Aggregate journal lines grouped by account_id (string)
        agg_sub = (
            select(
                JournalEntryLineModel.account_id.label("account_id"),
                func.coalesce(func.sum(JournalEntryLineModel.debit_amount), 0).label("total_debit"),
                func.coalesce(func.sum(JournalEntryLineModel.credit_amount), 0).label(
                    "total_credit"
                ),
            )
            .join(
                JournalEntryModel,
                JournalEntryModel.id == JournalEntryLineModel.journal_entry_id,
            )
            .where(
                JournalEntryLineModel.tenant_id == tenant_id,
                JournalEntryModel.tenant_id == tenant_id,
                JournalEntryModel.entry_date >= from_date if from_date is not None else sa_true(),
                JournalEntryModel.entry_date <= to_date,
            )
            .group_by(JournalEntryLineModel.account_id)
        )

        totals_result = await self._session.execute(agg_sub)
        totals = totals_result.mappings().all()
        if not totals:
            return []

        # Step 2: Convert account_ids to UUID and fetch COA info (same pattern as trial balance)
        account_uuids: list[uuid.UUID] = []
        for row in totals:
            account_id = str(row["account_id"])
            try:
                account_uuids.append(uuid.UUID(account_id))
            except ValueError:
                continue

        if not account_uuids:
            return []

        coa_result = await self._session.execute(
            select(AccountModel).where(
                AccountModel.tenant_id == tenant_uuid,
                AccountModel.id.in_(tuple(account_uuids)),
                AccountModel.is_active.is_(True),
            )
        )
        account_map = {str(m.id): m for m in coa_result.scalars().all()}

        # Step 3: Combine aggregation results with COA metadata, sorted by code
        rows: list[ReportAccountLine] = []
        for row in totals:
            account_id = str(row["account_id"])
            account = account_map.get(account_id)
            if account is None:
                continue
            rows.append(
                ReportAccountLine(
                    account_id=account_id,
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type.value,
                    total_debit=self._to_decimal(row["total_debit"]),
                    total_credit=self._to_decimal(row["total_credit"]),
                )
            )

        rows.sort(key=lambda ln: ln.account_code)
        return rows

    # ── retained earnings ──────────────────────────────────────────────────

    async def get_historical_net_profit(
        self,
        *,
        tenant_id: str,
        as_of_date: date,
    ) -> Decimal:
        """Compute cumulative net profit from day 1 through *as_of_date*.

        Uses a two-step approach to avoid UUID/string join issues:
        1. Get all revenue+expense accounts from COA
        2. Sum their net amounts from journal_entry_lines
        """
        tenant_uuid = self._to_tenant_uuid(tenant_id)
        if tenant_uuid is None:
            return Decimal("0.00")

        # Step 1: Get revenue and expense account IDs from COA
        coa_result = await self._session.execute(
            select(AccountModel).where(
                AccountModel.tenant_id == tenant_uuid,
                AccountModel.is_active.is_(True),
                AccountModel.account_type.in_([AccountType.REVENUE, AccountType.EXPENSE]),
            )
        )
        coa_accounts = list(coa_result.scalars().all())

        if not coa_accounts:
            return Decimal("0.00")

        # Build mapping: account_id (str) → account_type
        id_to_type: dict[str, str] = {}
        for acc in coa_accounts:
            id_to_type[str(acc.id)] = acc.account_type.value

        # Step 2: Sum net amounts per account from journal_entry_lines
        stmt = (
            select(
                JournalEntryLineModel.account_id.label("account_id"),
                func.coalesce(
                    func.sum(
                        JournalEntryLineModel.debit_amount - JournalEntryLineModel.credit_amount
                    ),
                    0,
                ).label("net_amount"),
            )
            .join(
                JournalEntryModel,
                JournalEntryModel.id == JournalEntryLineModel.journal_entry_id,
            )
            .where(
                JournalEntryLineModel.tenant_id == tenant_id,
                JournalEntryModel.tenant_id == tenant_id,
                JournalEntryModel.entry_date <= as_of_date,
                JournalEntryLineModel.account_id.in_(list(id_to_type.keys())),
            )
            .group_by(JournalEntryLineModel.account_id)
        )

        result = await self._session.execute(stmt)
        rows = result.mappings().all()

        revenue_net = Decimal("0.00")
        expense_net = Decimal("0.00")
        for row in rows:
            account_id = str(row["account_id"])
            atype = id_to_type.get(account_id)
            net = self._to_decimal(row["net_amount"])
            if atype == "revenue":
                revenue_net += net
            elif atype == "expense":
                expense_net += net

        # net_profit = -revenue_net - expense_net
        return -revenue_net - expense_net
