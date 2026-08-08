from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from accounting_shared.audit_client import AuditHttpClient, CreateAuditLogDTO
from accounting_shared.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from accounting_shared.middleware.audit_context import get_audit_context
from ledger_service.modules.ledger.application.dto import (
    AccountingPeriodDTO,
    AccountLedgerTransactionDTO,
    AccountLedgerViewDTO,
    CloseFiscalYearResponseDTO,
    CreateAccountingPeriodDTO,
    CreateJournalEntryDTO,
    JournalEntryDTO,
    JournalEntryLineDTO,
    TrialBalanceAccountDTO,
    TrialBalanceDTO,
)
from ledger_service.modules.ledger.domain.entities import (
    AccountingPeriod,
    JournalEntry,
    JournalEntryLine,
)
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
        audit_client: AuditHttpClient | None = None,
    ) -> None:
        self._journal_repo = journal_repo
        self._period_repo = period_repo
        self._audit_client = audit_client

    def _emit_audit(self, *, tenant_id: str, entity_type: str, action: str, entity_id: str) -> None:
        """Fire-and-forget audit emission; requires a request-scoped user id."""
        if self._audit_client is None:
            return
        user_id = get_audit_context().user_id
        if user_id is None:
            return
        self._audit_client.log_in_background(
            CreateAuditLogDTO(
                tenant_id=UUID(tenant_id),
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )

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
                    created_at=row.created_at,
                )
            )

        return AccountLedgerViewDTO(
            account_id=account_id,
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
        as_of_date: date | None = None,
    ) -> TrialBalanceDTO:
        rows = await self._journal_repo.get_trial_balance_rows(
            tenant_id=tenant_id, as_of_date=as_of_date
        )
        total_debit = _ZERO
        total_credit = _ZERO
        accounts: list[TrialBalanceAccountDTO] = []
        for row in rows:
            net = row.total_debit - row.total_credit
            debit_balance = net if net > _ZERO else _ZERO
            credit_balance = abs(net) if net < _ZERO else _ZERO
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
            total_debit += debit_balance
            total_credit += credit_balance

        return TrialBalanceDTO(
            as_of_date=as_of_date,
            accounts=accounts,
            total_debit_balance=total_debit,
            total_credit_balance=total_credit,
            is_balanced=total_debit == total_credit,
            imbalance=total_debit - total_credit,
        )

    async def create_journal_entry(
        self,
        dto: CreateJournalEntryDTO,
        tenant_id: str,
    ) -> JournalEntryDTO:
        _validate_lines(dto)

        if self._period_repo is None:
            raise ServiceUnavailableError("Accounting period repository is not configured.")

        try:
            tenant_uuid = UUID(tenant_id)
        except ValueError as e:
            raise ValidationError("Invalid tenant_id.") from e

        if await self._period_repo.is_date_closed(tenant_uuid, dto.entry_date):
            raise ConflictError(
                f"The date {dto.entry_date} falls within a closed accounting period."
            )

        account_ids = {line.account_id for line in dto.lines}
        for aid in account_ids:
            snap = await self._journal_repo.get_account_snapshot(
                tenant_id=tenant_id, account_id=aid
            )
            if snap is None:
                raise ValidationError(f"Account '{aid}' not found in Chart of Accounts.")

        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=dto.entry_date,
            reference=dto.reference,
            description=dto.description,
            source_type="manual",
        )
        for line_dto in dto.lines:
            entry.lines.append(
                JournalEntryLine(
                    tenant_id=tenant_id,
                    journal_entry_id=entry.id,
                    account_id=line_dto.account_id,
                    debit_amount=line_dto.debit_amount,
                    credit_amount=line_dto.credit_amount,
                    description=line_dto.description,
                )
            )

        created = await self._journal_repo.create(entry)
        self._emit_audit(
            tenant_id=tenant_id,
            entity_type="journal_entry",
            action="reversed" if created.is_reversal else "created",
            entity_id=created.id,
        )
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

    # --- Accounting Period methods ---

    async def create_period(
        self, tenant_id: str, dto: CreateAccountingPeriodDTO, user_id: str
    ) -> AccountingPeriodDTO:
        if self._period_repo is None:
            raise ServiceUnavailableError("Period repository not available.")
        if dto.start_date > dto.end_date:
            raise ValidationError("start_date must be on or before end_date.")
        existing = await self._period_repo.find_by_date_range(
            UUID(tenant_id), dto.start_date, dto.end_date
        )
        if existing is not None:
            raise ConflictError(
                f"A period already exists that overlaps {dto.start_date} to {dto.end_date}."
            )
        period = AccountingPeriod(
            tenant_id=UUID(tenant_id),
            start_date=dto.start_date,
            end_date=dto.end_date,
        )
        created = await self._period_repo.create_period(period)
        return AccountingPeriodDTO(
            id=str(created.id),
            start_date=created.start_date,
            end_date=created.end_date,
            is_closed=created.is_closed,
            closed_by=str(created.closed_by) if created.closed_by else None,
            created_at=created.created_at,
        )

    async def list_periods(self, tenant_id: str) -> list[AccountingPeriodDTO]:
        if self._period_repo is None:
            return []
        periods = await self._period_repo.list_by_tenant(UUID(tenant_id))
        return [
            AccountingPeriodDTO(
                id=str(p.id),
                start_date=p.start_date,
                end_date=p.end_date,
                is_closed=p.is_closed,
                closed_by=str(p.closed_by) if p.closed_by else None,
                created_at=p.created_at,
            )
            for p in periods
        ]

    async def get_current_period(self, tenant_id: str) -> AccountingPeriodDTO | None:
        if self._period_repo is None:
            return None
        period = await self._period_repo.find_by_date(UUID(tenant_id), date.today())
        if period is None:
            return None
        return AccountingPeriodDTO(
            id=str(period.id),
            start_date=period.start_date,
            end_date=period.end_date,
            is_closed=period.is_closed,
            closed_by=str(period.closed_by) if period.closed_by else None,
            created_at=period.created_at,
        )

    async def get_period(self, tenant_id: str, period_id: str) -> AccountingPeriodDTO:
        if self._period_repo is None:
            raise ServiceUnavailableError("Period repository not available.")
        try:
            period_uuid = UUID(period_id)
        except ValueError as e:
            raise ValidationError("Invalid accounting period ID.") from e
        period = await self._period_repo.find_by_id(UUID(tenant_id), period_uuid)
        if period is None:
            raise NotFoundError("Accounting period not found.")
        return AccountingPeriodDTO(
            id=str(period.id),
            start_date=period.start_date,
            end_date=period.end_date,
            is_closed=period.is_closed,
            closed_by=str(period.closed_by) if period.closed_by else None,
            created_at=period.created_at,
        )

    # --- Fiscal Year Close ---

    async def close_fiscal_year(
        self, tenant_id: str, period_id: str, user_id: str
    ) -> CloseFiscalYearResponseDTO:
        if self._period_repo is None:
            raise ServiceUnavailableError("Period repository not available.")

        tenant_uuid = UUID(tenant_id)
        try:
            period_uuid = UUID(period_id)
        except ValueError as e:
            raise ValidationError("Invalid accounting period ID.") from e

        period = await self._period_repo.find_by_id(tenant_uuid, period_uuid)
        if period is None:
            raise NotFoundError("Accounting period not found.")
        if period.is_closed:
            raise ConflictError("This fiscal year is already closed.")

        tb_rows = await self._journal_repo.get_trial_balance_rows(
            tenant_id=tenant_id,
            as_of_date=period.end_date,
            from_date=period.start_date,
        )
        pnl_rows = [
            r
            for r in tb_rows
            if r.account_type in ("revenue", "expense")
            and (r.total_debit != _ZERO or r.total_credit != _ZERO)
        ]

        re_snapshot = await self._period_repo.find_account_by_code(tenant_uuid, "3100")
        if re_snapshot is None:
            raise ValidationError(
                "Retained Earnings account (code 3100) not found. "
                "Please create it before closing the year."
            )
        re_account_id = re_snapshot.id

        lines: list[JournalEntryLine] = []
        for row in pnl_rows:
            net_balance = row.total_debit - row.total_credit
            if net_balance == _ZERO:
                continue
            if row.account_type == "revenue":
                if net_balance < 0:
                    amount = abs(net_balance)
                    lines.append(
                        JournalEntryLine(
                            account_id=row.account_id,
                            debit_amount=amount,
                            credit_amount=_ZERO,
                            description=f"Close revenue {row.account_code} {row.account_name}",
                        )
                    )
                elif net_balance > 0:
                    lines.append(
                        JournalEntryLine(
                            account_id=row.account_id,
                            debit_amount=_ZERO,
                            credit_amount=net_balance,
                            description=f"Close revenue debit balance {row.account_code}",
                        )
                    )
            elif row.account_type == "expense":
                if net_balance > 0:
                    lines.append(
                        JournalEntryLine(
                            account_id=row.account_id,
                            debit_amount=_ZERO,
                            credit_amount=net_balance,
                            description=f"Close expense {row.account_code} {row.account_name}",
                        )
                    )
                elif net_balance < 0:
                    lines.append(
                        JournalEntryLine(
                            account_id=row.account_id,
                            debit_amount=abs(net_balance),
                            credit_amount=_ZERO,
                            description=f"Close expense credit balance {row.account_code}",
                        )
                    )

        total_debits = sum((line.debit_amount for line in lines), _ZERO)
        total_credits = sum((line.credit_amount for line in lines), _ZERO)

        closing_entry: JournalEntry | None = None

        if lines:
            if total_credits > _ZERO:
                lines.append(
                    JournalEntryLine(
                        account_id=re_account_id,
                        debit_amount=total_credits,
                        credit_amount=_ZERO,
                        description="Year-end close to Retained Earnings",
                    )
                )
            if total_debits > _ZERO:
                lines.append(
                    JournalEntryLine(
                        account_id=re_account_id,
                        debit_amount=_ZERO,
                        credit_amount=total_debits,
                        description="Year-end close to Retained Earnings",
                    )
                )

            entry = JournalEntry(
                tenant_id=tenant_id,
                entry_date=period.end_date,
                reference=f"FY{period.end_date.year} Close",
                description=f"Year-end closing for period ending {period.end_date}",
                source_type="year_end_close",
                source_id=str(period.id),
                created_by=user_id,
                lines=lines,
            )
            closing_entry = await self._journal_repo.create(entry)
        else:
            entry = JournalEntry(
                tenant_id=tenant_id,
                entry_date=period.end_date,
                reference=f"FY{period.end_date.year} Close",
                description="Year-end closing — no P&L activity",
                source_type="year_end_close",
                source_id=str(period.id),
                created_by=user_id,
                lines=[
                    JournalEntryLine(
                        account_id=re_account_id,
                        debit_amount=_ZERO,
                        credit_amount=_ZERO,
                        description="No P&L activity",
                    ),
                    JournalEntryLine(
                        account_id=re_account_id,
                        debit_amount=_ZERO,
                        credit_amount=_ZERO,
                        description="No P&L activity",
                    ),
                ],
            )
            closing_entry = await self._journal_repo.create(entry)

        await self._period_repo.close_period(period_uuid, UUID(user_id))

        next_start = period.end_date + date.resolution
        try:
            next_end = period.end_date.replace(year=period.end_date.year + 1)
        except ValueError:
            # February 29 has no matching date in a non-leap year.
            next_end = period.end_date.replace(year=period.end_date.year + 1, day=28)
        next_period = AccountingPeriod(
            tenant_id=tenant_uuid,
            start_date=next_start,
            end_date=next_end,
        )
        created_next = await self._period_repo.create_period(next_period)

        return CloseFiscalYearResponseDTO(
            closing_journal_entry=_entity_to_dto(closing_entry) if closing_entry else None,
            period_id=str(period.id),
            next_period=AccountingPeriodDTO(
                id=str(created_next.id),
                start_date=created_next.start_date,
                end_date=created_next.end_date,
                is_closed=created_next.is_closed,
                closed_by=None,
                created_at=created_next.created_at,
            ),
            message=f"Fiscal year ending {period.end_date} closed successfully.",
        )


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
