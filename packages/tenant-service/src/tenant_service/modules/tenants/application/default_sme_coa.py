"""Singapore SME default chart of accounts for new tenants (US-2)."""

from __future__ import annotations

from coa_service.modules.coa.infrastructure.models import AccountType

# (code, name, account_type)
DEFAULT_SME_COA_SEED: list[tuple[str, str, AccountType]] = [
    ("1000", "Cash and Bank", AccountType.ASSET),
    ("1100", "Accounts Receivable", AccountType.ASSET),
    ("1200", "GST Input Tax", AccountType.ASSET),
    ("1300", "Prepayments", AccountType.ASSET),
    ("1500", "Fixed Assets", AccountType.ASSET),
    ("2000", "Accounts Payable", AccountType.LIABILITY),
    ("2100", "GST Output Tax", AccountType.LIABILITY),
    ("2200", "Accrued Expenses", AccountType.LIABILITY),
    ("2300", "Loans Payable", AccountType.LIABILITY),
    ("3000", "Share Capital", AccountType.EQUITY),
    ("3100", "Retained Earnings", AccountType.EQUITY),
    ("3200", "Opening Balance Equity", AccountType.EQUITY),
    ("4000", "Sales Revenue", AccountType.REVENUE),
    ("4100", "Service Revenue", AccountType.REVENUE),
    ("4200", "Other Income", AccountType.REVENUE),
    ("5000", "Cost of Goods Sold", AccountType.EXPENSE),
    ("6000", "Rent Expense", AccountType.EXPENSE),
    ("6100", "Salaries and Wages", AccountType.EXPENSE),
    ("6200", "Utilities Expense", AccountType.EXPENSE),
    ("6300", "Software and Subscriptions", AccountType.EXPENSE),
    ("6400", "Marketing Expense", AccountType.EXPENSE),
    ("6500", "Travel Expense", AccountType.EXPENSE),
    ("6600", "Bank Charges", AccountType.EXPENSE),
    ("6900", "Miscellaneous Expense", AccountType.EXPENSE),
]
