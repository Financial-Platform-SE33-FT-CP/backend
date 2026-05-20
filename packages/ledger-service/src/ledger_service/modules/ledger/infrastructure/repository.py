from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from accounting_shared.exceptions import ValidationError
from coa_service.modules.coa.infrastructure.models import AccountModel
from ledger_service.modules.ledger.domain.entities import (
    AccountingPeriod,
    AccountLedgerTransaction,
    JournalEntry,
    JournalEntryLine,
    LedgerAccountSnapshot,
    TrialBalanceAccountAggregate,
)
from ledger_service.modules.ledger.domain.repository import (
    AccountingPeriodRepository,
    JournalEntryRepository,
)
from ledger_service.modules.ledger.infrastructure.models import (
    AccountingPeriodModel,
    JournalEntryLineModel,
    JournalEntryModel,
)


def _model_to_entity(model: JournalEntryModel) -> JournalEntry:
    return JournalEntry(
        id=model.id,
        tenant_id=model.tenant_id,
        entry_date=model.entry_date,
        reference=model.reference,
        description=model.description or "",
        source_type=model.source_type or "manual",
        source_id=model.source_id,
        created_by=model.created_by or "",
        is_reversal=model.is_reversal,
        reversed_entry_id=model.reversed_entry_id,
        created_at=model.created_at,
        lines=[
            JournalEntryLine(
                id=line.id,
                tenant_id=line.tenant_id,
                journal_entry_id=line.journal_entry_id,
                account_id=line.account_id,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
                description=line.description or "",
            )
            for line in (model.lines or [])
        ],
    )


def _line_model_to_entity(line: JournalEntryLineModel) -> JournalEntryLine:
    return JournalEntryLine(
        id=line.id,
        tenant_id=line.tenant_id,
        journal_entry_id=line.journal_entry_id,
        account_id=line.account_id,
        debit_amount=line.debit_amount,
        credit_amount=line.credit_amount,
        description=line.description or "",
    )


def _period_model_to_entity(model: AccountingPeriodModel) -> AccountingPeriod:
    return AccountingPeriod(
        id=model.id,
        tenant_id=model.tenant_id,
        start_date=model.start_date,
        end_date=model.end_date,
        is_closed=model.is_closed,
        closed_by=model.closed_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyJournalEntryRepository(JournalEntryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: str, entry_id: str) -> JournalEntry | None:
        stmt = (
            select(JournalEntryModel)
            .where(JournalEntryModel.id == entry_id)
            .where(JournalEntryModel.tenant_id == tenant_id)
            .options(selectinload(JournalEntryModel.lines))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _model_to_entity(model)

    async def list_by_tenant(
        self,
        tenant_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> list[JournalEntry]:
        stmt = (
            select(JournalEntryModel)
            .where(JournalEntryModel.tenant_id == tenant_id)
            .order_by(JournalEntryModel.created_at.desc())
            .offset(offset)
            .limit(limit)
            .options(selectinload(JournalEntryModel.lines))
        )
        result = await self._session.execute(stmt)
        models = result.scalars().unique().all()
        return [_model_to_entity(m) for m in models]

    async def create(self, entry: JournalEntry) -> JournalEntry:
        model = JournalEntryModel(
            id=entry.id,
            tenant_id=entry.tenant_id,
            entry_date=entry.entry_date,
            reference=entry.reference,
            description=entry.description or None,
            source_type=entry.source_type,
            source_id=entry.source_id,
            created_by=entry.created_by or None,
            is_reversal=entry.is_reversal,
            reversed_entry_id=entry.reversed_entry_id,
            created_at=entry.created_at,
        )
        self._session.add(model)

        for line in entry.lines:
            line_model = JournalEntryLineModel(
                id=line.id,
                tenant_id=entry.tenant_id,
                journal_entry_id=entry.id,
                account_id=line.account_id,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
                description=line.description or None,
            )
            self._session.add(line_model)

        await self._session.flush()

        stmt = (
            select(JournalEntryModel)
            .where(JournalEntryModel.id == entry.id)
            .options(selectinload(JournalEntryModel.lines))
        )
        result = await self._session.execute(stmt)
        return _model_to_entity(result.scalar_one())

    async def get_account_snapshot(
        self,
        *,
        tenant_id: str,
        account_id: str,
    ) -> LedgerAccountSnapshot | None:
        try:
            tenant_uuid = uuid.UUID(tenant_id)
            account_uuid = uuid.UUID(account_id)
        except ValueError:
            return None

        result = await self._session.execute(
            select(AccountModel).where(
                AccountModel.tenant_id == tenant_uuid,
                AccountModel.id == account_uuid,
            )
        )
        model = result.scalars().first()
        if model is None:
            return None

        return LedgerAccountSnapshot(
            id=str(model.id),
            code=model.code,
            name=model.name,
            account_type=model.account_type.value,
        )

    async def get_account_balance_before(
        self,
        *,
        tenant_id: str,
        account_id: str,
        before_date: date,
    ) -> Decimal:
        stmt = (
            select(
                func.coalesce(
                    func.sum(
                        JournalEntryLineModel.debit_amount - JournalEntryLineModel.credit_amount
                    ),
                    0,
                )
            )
            .join(
                JournalEntryModel,
                JournalEntryModel.id == JournalEntryLineModel.journal_entry_id,
            )
            .where(
                JournalEntryLineModel.tenant_id == tenant_id,
                JournalEntryLineModel.account_id == account_id,
                JournalEntryModel.entry_date < before_date,
            )
        )
        result = await self._session.execute(stmt)
        return self._to_decimal(result.scalar_one())

    async def list_account_transactions(
        self,
        *,
        tenant_id: str,
        account_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> list[AccountLedgerTransaction]:
        stmt = (
            select(
                JournalEntryLineModel.id.label("journal_line_id"),
                JournalEntryLineModel.journal_entry_id,
                JournalEntryLineModel.debit_amount,
                JournalEntryLineModel.credit_amount,
                JournalEntryLineModel.description.label("line_description"),
                JournalEntryModel.entry_date,
                JournalEntryModel.reference,
                JournalEntryModel.source_type,
                JournalEntryModel.description.label("entry_description"),
                JournalEntryModel.created_at,
            )
            .join(
                JournalEntryModel,
                JournalEntryModel.id == JournalEntryLineModel.journal_entry_id,
            )
            .where(
                JournalEntryLineModel.tenant_id == tenant_id,
                JournalEntryLineModel.account_id == account_id,
            )
            .order_by(
                JournalEntryModel.entry_date.asc(),
                JournalEntryModel.created_at.asc(),
                JournalEntryLineModel.id.asc(),
            )
        )
        if from_date is not None:
            stmt = stmt.where(JournalEntryModel.entry_date >= from_date)
        if to_date is not None:
            stmt = stmt.where(JournalEntryModel.entry_date <= to_date)

        result = await self._session.execute(stmt)
        rows = result.mappings().all()

        return [
            AccountLedgerTransaction(
                journal_line_id=str(row["journal_line_id"]),
                journal_entry_id=str(row["journal_entry_id"]),
                entry_date=row["entry_date"],
                reference=str(row["reference"]),
                source_type=row["source_type"],
                entry_description=row["entry_description"],
                line_description=row["line_description"],
                debit_amount=self._to_decimal(row["debit_amount"]),
                credit_amount=self._to_decimal(row["credit_amount"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def get_trial_balance_rows(
        self,
        *,
        tenant_id: str,
        as_of_date: date | None,
    ) -> list[TrialBalanceAccountAggregate]:
        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except ValueError:
            return []

        stmt = (
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
            )
            .group_by(JournalEntryLineModel.account_id)
        )
        if as_of_date is not None:
            stmt = stmt.where(JournalEntryModel.entry_date <= as_of_date)

        totals_result = await self._session.execute(stmt)
        totals = totals_result.mappings().all()
        if not totals:
            return []

        account_uuid_by_id: dict[str, uuid.UUID] = {}
        for row in totals:
            account_id = str(row["account_id"])
            try:
                account_uuid_by_id[account_id] = uuid.UUID(account_id)
            except ValueError:
                continue

        if not account_uuid_by_id:
            return []

        accounts_result = await self._session.execute(
            select(AccountModel).where(
                AccountModel.tenant_id == tenant_uuid,
                AccountModel.id.in_(tuple(account_uuid_by_id.values())),
            )
        )
        account_map = {str(model.id): model for model in accounts_result.scalars().all()}

        rows: list[TrialBalanceAccountAggregate] = []
        for row in totals:
            account_id = str(row["account_id"])
            account = account_map.get(account_id)
            if account is None:
                continue
            rows.append(
                TrialBalanceAccountAggregate(
                    account_id=account_id,
                    account_code=account.code,
                    account_name=account.name,
                    account_type=account.account_type.value,
                    total_debit=self._to_decimal(row["total_debit"]),
                    total_credit=self._to_decimal(row["total_credit"]),
                )
            )

        rows.sort(key=lambda item: item.account_code)
        return rows

    async def create_opening_entry(
        self,
        *,
        tenant_id: str,
        entry_date: date,
        reference: str,
        description: str,
        source_type: str,
        created_by: str | None,
        lines: list[dict[str, Any]],
    ) -> str:
        if not lines:
            raise ValidationError("Journal entry must have at least one line.")

        total_debit = sum((Decimal(str(line["debit_amount"])) for line in lines), Decimal("0"))
        total_credit = sum((Decimal(str(line["credit_amount"])) for line in lines), Decimal("0"))
        if total_debit != total_credit:
            msg = "Journal entry lines must balance before posting."
            raise ValidationError(msg)

        entry_id = str(uuid4())
        now = datetime.utcnow()
        header = JournalEntryModel(
            id=entry_id,
            tenant_id=tenant_id,
            entry_date=entry_date,
            reference=reference,
            description=description,
            source_type=source_type,
            source_id=None,
            created_by=created_by,
            is_reversal=False,
            reversed_entry_id=None,
            created_at=now,
        )
        self._session.add(header)

        for line in lines:
            debit = Decimal(str(line["debit_amount"])).quantize(Decimal("0.01"))
            credit = Decimal(str(line["credit_amount"])).quantize(Decimal("0.01"))
            if debit > 0 and credit > 0:
                raise ValidationError("Line cannot have both debit and credit.")
            self._session.add(
                JournalEntryLineModel(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    journal_entry_id=entry_id,
                    account_id=str(line["account_id"]),
                    debit_amount=debit,
                    credit_amount=credit,
                    description=line.get("description"),
                )
            )

        await self._session.flush()
        return entry_id

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if value is None:
            return Decimal("0.00")
        return Decimal(str(value))


class SqlAlchemyAccountingPeriodRepository(AccountingPeriodRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_date(self, tenant_id: UUID, target_date: date) -> AccountingPeriod | None:
        stmt = (
            select(AccountingPeriodModel)
            .where(AccountingPeriodModel.tenant_id == tenant_id)
            .where(AccountingPeriodModel.start_date <= target_date)
            .where(AccountingPeriodModel.end_date >= target_date)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return _period_model_to_entity(model)

    async def is_date_closed(self, tenant_id: UUID, target_date: date) -> bool:
        period = await self.find_by_date(tenant_id, target_date)
        return period is not None and period.is_closed
