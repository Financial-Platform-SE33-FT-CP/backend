# Bank Statement CSV Fixtures for Manual Testing

These sample CSV files are designed for manual testing of the US-13 bank statement upload endpoint.

## Files

| File | Format | Columns | Suitable For |
|------|--------|---------|-------------|
| `bank_statement_standard.csv` | Simple | `date,description,amount` | Quick sanity check |
| `bank_statement_debit_credit.csv` | Singapore banks | `Date,Description,Debit,Credit` | Testing multi-column layout |
| `bank_statement_ocbc.csv` | OCBC-style | `Transaction Date,Particulars,Withdrawal,Deposit` | Testing Withdrawal/Deposit format |
| `bank_statement_dbs.csv` | DBS/POSB-style | `Transaction Date,Narration,Debit,Credit` | Testing Debit/Credit format |

## Manual Testing with cURL

### 1. Ensure the AR-AP service is running

```bash
cd backend && uv run --package ar-ap-service uvicorn ar_ap_service.main:app --reload --port 8006
```

### 2. Upload a CSV (replace placeholders)

```bash
# Read a CSV file, escape it as a JSON string, and POST it
CSV=$(cat packages/ar-ap-service/tests/fixtures/bank_statement_standard.csv | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")

curl -X POST http://localhost:8006/ar-ap/bank-statements/upload \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: <your-tenant-id>" \
  -H "Authorization: Bearer <your-jwt>" \
  -d "{
    \"bank_account_id\": \"<bank-account-uuid>\",
    \"csv_content\": $CSV
  }"
```

Required headers:
- `X-Tenant-ID`: UUID of the tenant
- `Authorization: Bearer <jwt>`: Valid JWT from auth-service
- `bank_account_id`: UUID of an existing bank account in the tenant

### 3. List unmatched transactions

```bash
curl http://localhost:8006/ar-ap/bank-transactions/unmatched \
  -H "X-Tenant-ID: <your-tenant-id>" \
  -H "Authorization: Bearer <your-jwt>"
```

### 4. Check reconciliation suggestions

```bash
curl http://localhost:8006/ar-ap/bank-transactions/{transaction_id}/suggestions \
  -H "X-Tenant-ID: <your-tenant-id>" \
  -H "Authorization: Bearer <your-jwt>"
```

### 5. Confirm a reconciliation match

```bash
curl -X POST http://localhost:8006/ar-ap/bank-transactions/reconcile \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: <your-tenant-id>" \
  -H "Authorization: Bearer <your-jwt>" \
  -d '{
    "transaction_id": "<bank-transaction-uuid>",
    "match_type": "invoice",
    "match_id": "<invoice-or-payment-uuid>",
    "account_id": "<bank-cash-account-uuid>"
  }'
```

## Parse verification

To verify any CSV file parses correctly without starting the service:

```bash
cd packages/ar-ap-service && uv run python3 -c "
from ar_ap_service.modules.ar_ap.application.bank_statement import parse_bank_statement_csv
content = open('tests/fixtures/bank_statement_standard.csv').read()
txns = parse_bank_statement_csv(content)
for t in txns:
    print(f'{t.date} | {t.description[:40]:40s} | {str(t.amount):>10s}')
"
```
