from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from ledger_service.modules.ledger.domain.entities import (
    AccountLedgerTransaction,
    JournalEntry,
    LedgerAccountSnapshot,
    TrialBalanceAccountAggregate,
)


class JournalEntryRepository(ABC):

    @abstractmethod
    async def get_by_id(self, entry_id: str) -> JournalEntry:
        ...

    @abstractmethod
    async def list_by_tenant(self, tenant_id: str) -> list[JournalEntry]:
        ...

    @abstractmethod
    async def create(self, entry: JournalEntry) -> JournalEntry:
        ...

    @abstractmethod
    async def get_account_snapshot(
        self,
        *,
        tenant_id: str,
        account_id: str,
    ) -> LedgerAccountSnapshot | None:
        ...

    @abstractmethod
    async def get_account_balance_before(
        self,
        *,
        tenant_id: str,
        account_id: str,
        before_date: date,
    ) -> Decimal:
        ...

    @abstractmethod
    async def list_account_transactions(
        self,
        *,
        tenant_id: str,
        account_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> list[AccountLedgerTransaction]:
        ...

    @abstractmethod
    async def get_trial_balance_rows(
        self,
        *,
        tenant_id: str,
        as_of_date: date | None,
    ) -> list[TrialBalanceAccountAggregate]:
        ...
