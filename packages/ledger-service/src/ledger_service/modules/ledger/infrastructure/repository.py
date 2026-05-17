from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ledger_service.modules.ledger.domain.entities import (
    AccountingPeriod,
    JournalEntry,
    JournalEntryLine,
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


class SqlAlchemyAccountingPeriodRepository(AccountingPeriodRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_date(
        self, tenant_id: UUID, target_date: date
    ) -> AccountingPeriod | None:
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
