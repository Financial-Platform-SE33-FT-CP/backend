from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class JournalEntryCreateRequest(BaseModel):
    tenant_id: str
    entry_date: date
    reference: str
    description: str | None = None


class JournalEntryResponse(BaseModel):
    id: str
    tenant_id: str
    entry_date: date
    reference: str
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True
