from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    journal_entry_id: str
    account_id: str
    debit_amount: Decimal
    credit_amount: Decimal
    description: str


class JournalEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class JournalEntryListResponse(BaseModel):
    entries: list[JournalEntryResponse]
    count: int
    offset: int
    limit: int


class AccountLedgerTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    journal_line_id: str
    journal_entry_id: str
    entry_date: date
    reference: str
    source_type: str | None
    entry_description: str | None
    line_description: str | None
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal


class AccountLedgerViewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_code: str
    account_name: str
    account_type: str
    from_date: date | None
    to_date: date | None
    opening_balance: Decimal
    closing_balance: Decimal
    transactions: list[AccountLedgerTransactionResponse]


class TrialBalanceAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    account_code: str
    account_name: str
    account_type: str
    total_debit: Decimal
    total_credit: Decimal
    debit_balance: Decimal
    credit_balance: Decimal


class TrialBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date | None
    accounts: list[TrialBalanceAccountResponse]
    total_debit_balance: Decimal
    total_credit_balance: Decimal
    is_balanced: bool
    imbalance: Decimal


class AccountingPeriodCreate(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_date_range(self) -> "AccountingPeriodCreate":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class AccountingPeriodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    start_date: date
    end_date: date
    is_closed: bool
    closed_by: str | None = None
    created_at: datetime


class CloseFiscalYearResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    closing_journal_entry: JournalEntryResponse | None = None
    period_id: str
    next_period: AccountingPeriodResponse | None = None
    message: str
