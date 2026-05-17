from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.exceptions import NotFoundError, ValidationError

from ledger_service.modules.ledger.domain.entities import JournalEntry
from ledger_service.modules.ledger.domain.repository import JournalEntryRepository
from ledger_service.modules.ledger.infrastructure.models import (
    JournalEntryLineModel,
    JournalEntryModel,
)


class SqlAlchemyJournalEntryRepository(JournalEntryRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, entry_id: str) -> JournalEntry:
        result = await self._session.execute(
            select(JournalEntryModel).where(JournalEntryModel.id == entry_id)
        )
        model = result.scalars().first()
        if model is None:
            raise NotFoundError("Journal entry not found.")
        return self._to_domain(model)

    async def list_by_tenant(self, tenant_id: str) -> list[JournalEntry]:
        result = await self._session.execute(
            select(JournalEntryModel)
            .where(JournalEntryModel.tenant_id == tenant_id)
            .order_by(JournalEntryModel.entry_date.desc())
        )
        return [self._to_domain(m) for m in result.scalars().all()]

    async def create(self, entry: JournalEntry) -> JournalEntry:
        model = JournalEntryModel(
            id=entry.id,
            tenant_id=entry.tenant_id,
            entry_date=entry.entry_date,
            reference=entry.reference,
            description=entry.description,
            created_at=entry.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return entry

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

        total_debit = sum(
            (Decimal(str(line["debit_amount"])) for line in lines), Decimal("0")
        )
        total_credit = sum(
            (Decimal(str(line["credit_amount"])) for line in lines), Decimal("0")
        )
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
    def _to_domain(model: JournalEntryModel) -> JournalEntry:
        return JournalEntry(
            id=model.id,
            tenant_id=model.tenant_id,
            entry_date=model.entry_date,
            reference=model.reference,
            description=model.description or "",
            created_at=model.created_at,
        )
