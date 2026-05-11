from accounting_shared.config import SharedSettings


class COASettings(SharedSettings):
    default_coa_accounts: list[dict] = [
        {
            "code": "1000",
            "name": "Cash",
            "type": "asset",
            "description": "Cash and cash equivalents",
        },
        {
            "code": "1200",
            "name": "Accounts Receivable",
            "type": "asset",
            "description": "Trade receivables",
        },
        {
            "code": "2000",
            "name": "Accounts Payable",
            "type": "liability",
            "description": "Short-term payables",
        },
        {
            "code": "3000",
            "name": "Owner's Equity",
            "type": "equity",
            "description": "Owner's capital",
        },
        {"code": "4000", "name": "Revenue", "type": "revenue", "description": "Operating revenue"},
        {
            "code": "5000",
            "name": "Operating Expenses",
            "type": "expense",
            "description": "General operating expenses",
        },
    ]
