from datetime import date
from decimal import Decimal
from uuid import UUID

from accounting_shared.exceptions import ConflictError, ValidationError
from ledger_service.modules.ledger.application.dto import (
    CreateJournalEntryDTO,
    JournalEntryDTO,
    JournalEntryLineDTO,
)
from ledger_service.modules.ledger.domain.entities import JournalEntry, JournalEntryLine
from ledger_service.modules.ledger.domain.repository import (
    AccountingPeriodRepository,
    JournalEntryRepository,
)


def _entity_to_dto(entry: JournalEntry) -> JournalEntryDTO:
    return JournalEntryDTO(
        id=entry.id,
        tenant_id=entry.tenant_id,
        entry_date=entry.entry_date,
        reference=entry.reference,
        description=entry.description,
        source_type=entry.source_type,
        source_id=entry.source_id,
        created_by=entry.created_by,
        is_reversal=entry.is_reversal,
        reversed_entry_id=entry.reversed_entry_id,
        created_at=entry.created_at,
        lines=[
            JournalEntryLineDTO(
                id=line.id,
                tenant_id=line.tenant_id,
                journal_entry_id=line.journal_entry_id,
                account_id=line.account_id,
                debit_amount=line.debit_amount,
                credit_amount=line.credit_amount,
                description=line.description,
            )
            for line in entry.lines
        ],
    )


class LedgerService:

    def __init__(
        self,
        journal_repo: JournalEntryRepository,
        period_repo: AccountingPeriodRepository,
    ) -> None:
        self._journal_repo = journal_repo
        self._period_repo = period_repo

    async def create_journal_entry(
        self,
        dto: CreateJournalEntryDTO,
        tenant_id: str,
        created_by: str = "",
    ) -> JournalEntryDTO:
        _validate_lines(dto)

        tenant_uuid = UUID(tenant_id)
        is_closed = await self._period_repo.is_date_closed(tenant_uuid, dto.entry_date)
        if is_closed:
            raise ConflictError(
                f"Cannot post journal entry: date {dto.entry_date} "
                "falls within a closed accounting period."
            )

        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=dto.entry_date,
            reference=dto.reference,
            description=dto.description or "",
            source_type="manual",
            created_by=created_by,
            lines=[
                JournalEntryLine(
                    tenant_id=tenant_id,
                    account_id=line.account_id,
                    debit_amount=line.debit_amount or Decimal("0.00"),
                    credit_amount=line.credit_amount or Decimal("0.00"),
                    description=line.description or "",
                )
                for line in dto.lines
            ],
        )

        if not entry.is_balanced:
            raise ValidationError(
                f"Journal entry is not balanced: "
                f"debit {entry.total_debit}, credit {entry.total_credit}"
            )

        created = await self._journal_repo.create(entry)
        return _entity_to_dto(created)

    async def get_journal_entry(
        self, tenant_id: str, entry_id: str
    ) -> JournalEntryDTO | None:
        entry = await self._journal_repo.get_by_id(tenant_id, entry_id)
        if entry is None:
            return None
        return _entity_to_dto(entry)

    async def list_journal_entries(
        self,
        tenant_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> list[JournalEntryDTO]:
        entries = await self._journal_repo.list_by_tenant(tenant_id, offset, limit)
        return [_entity_to_dto(e) for e in entries]


def _validate_lines(dto: CreateJournalEntryDTO) -> None:
    if len(dto.lines) < 2:
        raise ValidationError(
            "A journal entry must have at least 2 lines."
        )

    for i, line in enumerate(dto.lines):
        debit = line.debit_amount or Decimal("0.00")
        credit = line.credit_amount or Decimal("0.00")

        if debit < 0 or credit < 0:
            raise ValidationError(
                f"Line {i + 1}: amounts must not be negative."
            )

        if debit > 0 and credit > 0:
            raise ValidationError(
                f"Line {i + 1}: a journal line cannot have both debit and credit amounts."
            )

        if debit == 0 and credit == 0:
            raise ValidationError(
                f"Line {i + 1}: a journal line must have either a debit or credit amount."
            )

    total_debit = sum(
        (l.debit_amount or Decimal("0.00") for l in dto.lines), Decimal("0.00")
    )
    total_credit = sum(
        (l.credit_amount or Decimal("0.00") for l in dto.lines), Decimal("0.00")
    )

    if total_debit == 0 and total_credit == 0:
        raise ValidationError(
            "Journal entry must have at least one non-zero amount."
        )

    if total_debit != total_credit:
        raise ValidationError(
            f"Journal entry is not balanced: "
            f"debit {total_debit}, credit {total_credit}"
        )
