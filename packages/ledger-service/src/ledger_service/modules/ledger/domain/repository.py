from abc import ABC, abstractmethod
from datetime import date
from uuid import UUID

from ledger_service.modules.ledger.domain.entities import AccountingPeriod, JournalEntry


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


class AccountingPeriodRepository(ABC):

    @abstractmethod
    async def find_by_date(
        self, tenant_id: UUID, target_date: date
    ) -> AccountingPeriod | None:
        """Find the accounting period that contains *target_date*."""

    @abstractmethod
    async def is_date_closed(self, tenant_id: UUID, target_date: date) -> bool:
        """Return True if *target_date* falls within a closed accounting period."""
