from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from accounting_shared.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from ledger_service.modules.ledger.application.dto import (
    AccountLedgerTransactionDTO,
    AccountLedgerViewDTO,
    CreateJournalEntryDTO,
    JournalEntryDTO,
    JournalEntryLineDTO,
    TrialBalanceAccountDTO,
    TrialBalanceDTO,
)
from ledger_service.modules.ledger.domain.entities import JournalEntry, JournalEntryLine
from ledger_service.modules.ledger.domain.repository import (
    AccountingPeriodRepository,
    JournalEntryRepository,
)

_ZERO = Decimal("0.00")


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
        period_repo: AccountingPeriodRepository | None = None,
    ) -> None:
        self._journal_repo = journal_repo
        self._period_repo = period_repo

    async def get_account_transactions(
        self,
        *,
        tenant_id: str,
        account_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> AccountLedgerViewDTO:
        if from_date and to_date and from_date > to_date:
            raise ValidationError("from_date cannot be after to_date.")

        account = await self._journal_repo.get_account_snapshot(
            tenant_id=tenant_id,
            account_id=account_id,
        )
        if account is None:
            raise NotFoundError("Account not found.")

        opening_balance = _ZERO
        if from_date is not None:
            opening_balance = await self._journal_repo.get_account_balance_before(
                tenant_id=tenant_id,
                account_id=account_id,
                before_date=from_date,
            )

        rows = await self._journal_repo.list_account_transactions(
            tenant_id=tenant_id,
            account_id=account_id,
            from_date=from_date,
            to_date=to_date,
        )

        running_balance = opening_balance
        transactions: list[AccountLedgerTransactionDTO] = []
        for row in rows:
            running_balance += row.debit_amount - row.credit_amount
            transactions.append(
                AccountLedgerTransactionDTO(
                    journal_line_id=row.journal_line_id,
                    journal_entry_id=row.journal_entry_id,
                    entry_date=row.entry_date,
                    reference=row.reference,
                    source_type=row.source_type,
                    entry_description=row.entry_description,
                    line_description=row.line_description,
                    debit_amount=row.debit_amount,
                    credit_amount=row.credit_amount,
                    running_balance=running_balance,
                )
            )

        return AccountLedgerViewDTO(
            account_id=account.id,
            account_code=account.code,
            account_name=account.name,
            account_type=account.account_type,
            from_date=from_date,
            to_date=to_date,
            opening_balance=opening_balance,
            closing_balance=running_balance,
            transactions=transactions,
        )

    async def get_trial_balance(
        self,
        *,
        tenant_id: str,
        as_of_date: date | None,
    ) -> TrialBalanceDTO:
        rows = await self._journal_repo.get_trial_balance_rows(
            tenant_id=tenant_id,
            as_of_date=as_of_date,
        )

        accounts: list[TrialBalanceAccountDTO] = []
        total_debit_balance = _ZERO
        total_credit_balance = _ZERO

        for row in rows:
            net_amount = row.total_debit - row.total_credit
            debit_balance = net_amount if net_amount > _ZERO else _ZERO
            credit_balance = -net_amount if net_amount < _ZERO else _ZERO

            total_debit_balance += debit_balance
            total_credit_balance += credit_balance

            accounts.append(
                TrialBalanceAccountDTO(
                    account_id=row.account_id,
                    account_code=row.account_code,
                    account_name=row.account_name,
                    account_type=row.account_type,
                    total_debit=row.total_debit,
                    total_credit=row.total_credit,
                    debit_balance=debit_balance,
                    credit_balance=credit_balance,
                )
            )

        imbalance = total_debit_balance - total_credit_balance
        return TrialBalanceDTO(
            as_of_date=as_of_date,
            accounts=accounts,
            total_debit_balance=total_debit_balance,
            total_credit_balance=total_credit_balance,
            is_balanced=imbalance == _ZERO,
            imbalance=imbalance,
        )

    async def create_journal_entry(
        self,
        dto: CreateJournalEntryDTO,
        tenant_id: str,
        created_by: str = "",
    ) -> JournalEntryDTO:
        _validate_lines(dto)

        if self._period_repo is None:
            raise ServiceUnavailableError("Accounting period repository is not configured.")

        try:
            tenant_uuid = UUID(tenant_id)
        except ValueError as e:
            raise ValidationError("Invalid tenant_id.") from e

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
                    debit_amount=line.debit_amount or _ZERO,
                    credit_amount=line.credit_amount or _ZERO,
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

    async def get_journal_entry(self, tenant_id: str, entry_id: str) -> JournalEntryDTO | None:
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
        raise ValidationError("A journal entry must have at least 2 lines.")

    for i, line in enumerate(dto.lines):
        debit = line.debit_amount or _ZERO
        credit = line.credit_amount or _ZERO

        if debit < 0 or credit < 0:
            raise ValidationError(f"Line {i + 1}: amounts must not be negative.")

        if debit > _ZERO and credit > _ZERO:
            raise ValidationError(
                f"Line {i + 1}: a journal line cannot have both debit and credit amounts."
            )

        if debit == _ZERO and credit == _ZERO:
            raise ValidationError(
                f"Line {i + 1}: a journal line must have either a debit or credit amount."
            )

    total_debit = sum((ln.debit_amount or _ZERO for ln in dto.lines), _ZERO)
    total_credit = sum((ln.credit_amount or _ZERO for ln in dto.lines), _ZERO)

    if total_debit == _ZERO and total_credit == _ZERO:
        raise ValidationError("Journal entry must have at least one non-zero amount.")

    if total_debit != total_credit:
        raise ValidationError(
            f"Journal entry is not balanced: debit {total_debit}, credit {total_credit}"
        )
