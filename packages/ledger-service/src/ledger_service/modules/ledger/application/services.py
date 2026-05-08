from ledger_service.modules.ledger.application.dto import JournalEntryDTO


class LedgerService:

    async def create_journal_entry(self, dto: JournalEntryDTO) -> JournalEntryDTO:
        raise NotImplementedError

    async def get_trial_balance(self, tenant_id: str) -> dict:
        raise NotImplementedError
