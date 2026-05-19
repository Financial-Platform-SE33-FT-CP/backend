from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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