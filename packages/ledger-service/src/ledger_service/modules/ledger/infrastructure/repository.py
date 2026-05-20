from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from coa_service.modules.coa.infrastructure.models import AccountModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from accounting_shared.exceptions import NotFoundError, ValidationError

from ledger_service.modules.ledger.domain.entities import (
    AccountLedgerTransaction,
    JournalEntry,
    LedgerAccountSnapshot,
    TrialBalanceAccountAggregate,
)
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
                        JournalEntryLineModel.debit_amount
                        - JournalEntryLineModel.credit_amount
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
                func.coalesce(func.sum(JournalEntryLineModel.debit_amount), 0).label(
                    "total_debit"
                ),
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
        account_map = {
            str(model.id): model
            for model in accounts_result.scalars().all()
        }

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

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if value is None:
            return Decimal("0.00")
        return Decimal(str(value))
