from abc import ABC, abstractmethod

from ledger_service.modules.ledger.domain.entities import JournalEntry


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
