from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class JournalEntryDTO(BaseModel):
    id: str
    tenant_id: str
    entry_date: date
    reference: str
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class JournalEntryLineDTO(BaseModel):
    id: str
    journal_entry_id: str
    account_id: str
    debit_amount: Decimal
    credit_amount: Decimal
    description: str

    class Config:
        from_attributes = True
