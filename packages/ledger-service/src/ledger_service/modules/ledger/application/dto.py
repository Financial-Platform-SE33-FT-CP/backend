from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class JournalEntryLineDTO(BaseModel):
    id: str
    tenant_id: str
    journal_entry_id: str
    account_id: str
    debit_amount: Decimal
    credit_amount: Decimal
    description: str = ""

    model_config = {"from_attributes": True}


class JournalEntryDTO(BaseModel):
    id: str
    tenant_id: str
    entry_date: date
    reference: str
    description: str = ""
    source_type: str = "manual"
    source_id: str | None = None
    created_by: str = ""
    is_reversal: bool = False
    reversed_entry_id: str | None = None
    created_at: datetime
    lines: list[JournalEntryLineDTO] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CreateJournalEntryLineDTO(BaseModel):
    account_id: str
    debit_amount: Decimal = Field(default_factory=Decimal)
    credit_amount: Decimal = Field(default_factory=Decimal)
    description: str = ""


class CreateJournalEntryDTO(BaseModel):
    entry_date: date
    reference: str
    description: str = ""
    lines: list[CreateJournalEntryLineDTO] = Field(..., min_length=2)
