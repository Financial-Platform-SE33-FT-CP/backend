"""Cash Flow Statement account-code → section mapping.

Based on the Singapore SME COA seeded by tenant-service.
Each entry maps an ``account_code`` to a cash-flow section.
Accounts not listed here are excluded from the cash flow statement.

To customize: edit this dict or load from a configuration source in the future.
"""

from enum import StrEnum


class CFSection(StrEnum):
    """Sections of the indirect-method cash flow statement."""
    CASH = "cash_and_equivalents"
    OPERATING_ASSET = "operating_current_assets"
    OPERATING_LIABILITY = "operating_current_liabilities"
    INVESTING_ASSET = "investing_assets"
    FINANCING_LIABILITY = "financing_liabilities"
    EQUITY = "equity"
    NON_CASH_EXPENSE = "non_cash_expenses"


# ── Default mapping for SG SME COA ─────────────────────────────────────────────

DEFAULT_CF_MAPPING: dict[str, CFSection] = {
    # Cash & equivalents
    "1000": CFSection.CASH,
    # Operating — current assets (changes affect operating cash flow)
    "1100": CFSection.OPERATING_ASSET,   # Accounts Receivable
    "1200": CFSection.OPERATING_ASSET,   # GST Input Tax
    "1300": CFSection.OPERATING_ASSET,   # Prepayments
    # Operating — current liabilities
    "2000": CFSection.OPERATING_LIABILITY,   # Accounts Payable
    "2100": CFSection.OPERATING_LIABILITY,   # GST Output Tax
    "2200": CFSection.OPERATING_LIABILITY,   # Accrued Expenses
    # Investing
    "1500": CFSection.INVESTING_ASSET,   # Fixed Assets
    # Financing
    "2300": CFSection.FINANCING_LIABILITY,   # Loans Payable
    "3000": CFSection.EQUITY,               # Share Capital
}


def get_cf_section(account_code: str) -> CFSection | None:
    """Return the cash-flow section for *account_code*, or ``None`` if unclassified."""
    return DEFAULT_CF_MAPPING.get(account_code)
