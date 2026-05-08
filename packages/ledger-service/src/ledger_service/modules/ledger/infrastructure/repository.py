from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ledger_service.modules.ledger.domain.entities import JournalEntry
from ledger_service.modules.ledger.domain.repository import JournalEntryRepository
from ledger_service.modules.ledger.infrastructure.models import JournalEntryModel


class SqlAlchemyJournalEntryRepository(JournalEntryRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, entry_id: str) -> JournalEntry:
        raise NotImplementedError

    async def list_by_tenant(self, tenant_id: str) -> list[JournalEntry]:
        raise NotImplementedError

    async def create(self, entry: JournalEntry) -> JournalEntry:
        raise NotImplementedError
