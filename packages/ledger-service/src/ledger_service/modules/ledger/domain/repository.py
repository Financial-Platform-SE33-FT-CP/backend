from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from uuid import UUID

from ledger_service.modules.ledger.domain.entities import (
    AccountingPeriod,
    AccountLedgerTransaction,
    JournalEntry,
    LedgerAccountSnapshot,
    TrialBalanceAccountAggregate,
)


class JournalEntryRepository(ABC):
    @abstractmethod
    async def get_by_id(self, tenant_id: str, entry_id: str) -> JournalEntry | None:
        """Retrieve a journal entry with its lines, scoped to tenant."""

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> list[JournalEntry]:
        """List journal entries for a tenant, newest first."""

    @abstractmethod
    async def create(self, entry: JournalEntry) -> JournalEntry:
        """Persist a new journal entry with its lines in a single transaction."""

    @abstractmethod
    async def get_account_snapshot(
        self,
        *,
        tenant_id: str,
        account_id: str,
    ) -> LedgerAccountSnapshot | None: ...

    @abstractmethod
    async def get_account_balance_before(
        self,
        *,
        tenant_id: str,
        account_id: str,
        before_date: date,
    ) -> Decimal: ...

    @abstractmethod
    async def list_account_transactions(
        self,
        *,
        tenant_id: str,
        account_id: str,
        from_date: date | None,
        to_date: date | None,
    ) -> list[AccountLedgerTransaction]: ...

    @abstractmethod
    async def get_trial_balance_rows(
        self,
        *,
        tenant_id: str,
        as_of_date: date | None,
        from_date: date | None = None,
    ) -> list[TrialBalanceAccountAggregate]: ...


class AccountingPeriodRepository(ABC):
    @abstractmethod
    async def find_by_date(self, tenant_id: UUID, target_date: date) -> AccountingPeriod | None:
        """Find the accounting period that contains *target_date*."""

    @abstractmethod
    async def is_date_closed(self, tenant_id: UUID, target_date: date) -> bool:
        """Return True if *target_date* falls within a closed accounting period."""

    @abstractmethod
    async def find_account_by_code(
        self, tenant_id: UUID, code: str
    ) -> LedgerAccountSnapshot | None:
        """Find an account by its code, scoped to tenant."""

    @abstractmethod
    async def create_period(self, period: AccountingPeriod) -> AccountingPeriod:
        """Persist a new accounting period."""

    @abstractmethod
    async def list_by_tenant(self, tenant_id: UUID) -> list[AccountingPeriod]:
        """List all periods for a tenant, newest first."""

    @abstractmethod
    async def find_by_id(self, tenant_id: UUID, period_id: UUID) -> AccountingPeriod | None:
        """Find a period by its ID, scoped to tenant."""

    @abstractmethod
    async def find_by_date_range(
        self, tenant_id: UUID, start_date: date, end_date: date
    ) -> AccountingPeriod | None:
        """Return a period that overlaps the given date range, or None."""

    @abstractmethod
    async def close_period(self, period_id: UUID, closed_by: UUID) -> None:
        """Mark a period as closed."""
