from __future__ import annotations

from datetime import date
from decimal import Decimal

from accounting_shared.exceptions import NotFoundError, ValidationError

from ledger_service.modules.ledger.application.dto import (
    AccountLedgerTransactionDTO,
    AccountLedgerViewDTO,
    JournalEntryDTO,
    TrialBalanceAccountDTO,
    TrialBalanceDTO,
)
from ledger_service.modules.ledger.domain.repository import JournalEntryRepository

_ZERO = Decimal("0.00")


class LedgerService:
    def __init__(self, repository: JournalEntryRepository) -> None:
        self._repository = repository

    async def create_journal_entry(self, dto: JournalEntryDTO) -> JournalEntryDTO:
        raise NotImplementedError

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

        account = await self._repository.get_account_snapshot(
            tenant_id=tenant_id,
            account_id=account_id,
        )
        if account is None:
            raise NotFoundError("Account not found.")

        opening_balance = _ZERO
        if from_date is not None:
            opening_balance = await self._repository.get_account_balance_before(
                tenant_id=tenant_id,
                account_id=account_id,
                before_date=from_date,
            )

        rows = await self._repository.list_account_transactions(
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
        rows = await self._repository.get_trial_balance_rows(
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
