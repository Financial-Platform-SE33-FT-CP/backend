from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class JournalEntryLineCreate(BaseModel):
    account_id: str
    debit_amount: Decimal = Field(default_factory=Decimal)
    credit_amount: Decimal = Field(default_factory=Decimal)
    description: str = ""


class JournalEntryCreateRequest(BaseModel):
    entry_date: date
    reference: str
    description: str = ""
    lines: list[JournalEntryLineCreate] = Field(..., min_length=2)


class JournalEntryLineResponse(BaseModel):
    id: str
    tenant_id: str
    journal_entry_id: str
    account_id: str
    debit_amount: Decimal
    credit_amount: Decimal
    description: str

    model_config = {"from_attributes": True}


class JournalEntryResponse(BaseModel):
    id: str
    tenant_id: str
    entry_date: date
    reference: str
    description: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    created_by: str | None = None
    is_reversal: bool = False
    reversed_entry_id: str | None = None
    created_at: datetime
    lines: list[JournalEntryLineResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class JournalEntryListResponse(BaseModel):
    entries: list[JournalEntryResponse]
    count: int
    offset: int
    limit: int
