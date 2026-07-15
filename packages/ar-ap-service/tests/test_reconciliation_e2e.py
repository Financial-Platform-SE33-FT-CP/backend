"""End-to-end test: upload CSV → reconcile → verify journal entry.

Simulates the exact user manual testing flow using in-memory fakes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from ar_ap_service.config import ArApSettings
from ar_ap_service.modules.ar_ap.application.bank_statement import BankStatementService
from ar_ap_service.modules.ar_ap.application.dto import (
    CreateInvoiceCommand,
    InvoiceLineInput,
    ReconcileTransactionCommand,
    UploadBankStatementCommand,
)
from ar_ap_service.modules.ar_ap.application.reconciliation import ReconciliationService
from ar_ap_service.modules.ar_ap.application.services import InvoiceService
from ar_ap_service.modules.ar_ap.domain.entities import (
    AccountInfo,
    Customer,
    InvoiceStatus,
)

from .conftest import (
    AR_ACCOUNT_ID,
    BANK_ACCOUNT_ID,
    GST_ACCOUNT_ID,
    GST_OUTPUT_CODE_ID,
    REVENUE_ACCOUNT_ID,
    TENANT_A,
    FakeAccountReader,
    FakeBankTransactionRepository,
    FakeCustomerRepository,
    FakeGstRepository,
    FakeInvoiceRepository,
    FakeLedgerPoster,
    FakePaymentRepository,
)

ISSUE_DATE = date(2026, 4, 1)
DUE_DATE = date(2026, 4, 30)
USER_ID = uuid4()
SETTINGS = ArApSettings(
    tenant_internal_api_token="test-token",
    ar_control_account_code="1100",
    gst_output_account_code="2100",
    jwt_secret="test-secret",
)


@pytest.mark.asyncio
async def test_full_upload_csv_then_reconcile_e2e(
    gst: FakeGstRepository,
) -> None:
    """Full E2E: upload CSV → create invoice → issue → suggest → reconcile → verify."""
    # Build fakes
    bank_txns = FakeBankTransactionRepository()
    invoices = FakeInvoiceRepository()
    payments = FakePaymentRepository()
    ledger = FakeLedgerPoster()
    accounts = FakeAccountReader()
    customers = FakeCustomerRepository()

    # Seed accounts
    for tenant in (TENANT_A,):
        accounts.seed(
            tenant, AccountInfo(AR_ACCOUNT_ID, "1100", "Accounts Receivable", "asset", True)
        )
        accounts.seed(
            tenant, AccountInfo(GST_ACCOUNT_ID, "2100", "GST Output Tax", "liability", True)
        )
        accounts.seed(
            tenant, AccountInfo(REVENUE_ACCOUNT_ID, "4000", "Sales Revenue", "revenue", True)
        )
        accounts.seed(tenant, AccountInfo(BANK_ACCOUNT_ID, "1000", "Cash at Bank", "asset", True))

    # Seed customer
    customer = Customer(id=uuid4(), tenant_id=TENANT_A, name="Acme Pte Ltd")
    customers.seed(customer)
    customer_id = customer.id

    # Build services
    bank_stmt_svc = BankStatementService(bank_txn_repo=bank_txns)
    invoice_svc = InvoiceService(
        invoices=invoices,
        customers=customers,
        accounts=accounts,
        gst=gst,
        ledger=ledger,
        settings=SETTINGS,
    )
    reconciliation_svc = ReconciliationService(
        bank_txn_repo=bank_txns,
        invoice_repo=invoices,
        payment_repo=payments,
        ledger_poster=ledger,
        accounts=accounts,
        settings=SETTINGS,
    )

    # 1. Create and issue an invoice
    cmd = CreateInvoiceCommand(
        customer_id=customer_id,
        issue_date=ISSUE_DATE,
        due_date=DUE_DATE,
        lines=[
            InvoiceLineInput(
                account_id=REVENUE_ACCOUNT_ID,
                quantity=Decimal("10"),
                unit_price=Decimal("100"),
                description="Consulting",
                gst_code_id=GST_OUTPUT_CODE_ID,
                gst_rate=Decimal("0.09"),
            )
        ],
    )
    draft = await invoice_svc.create_draft(TENANT_A, cmd, USER_ID)
    assert draft.status == InvoiceStatus.DRAFT
    assert draft.total == Decimal("1090.00")

    issued = await invoice_svc.issue_invoice(TENANT_A, draft.id, USER_ID)
    assert issued.status == InvoiceStatus.ISSUED
    invoice_id = issued.id

    # 2. Upload CSV bank statement
    csv_content = "date,description,amount\n2026-04-01,Invoice payment - INV-0001,1090.00\n"
    upload_cmd = UploadBankStatementCommand(
        bank_account_id=BANK_ACCOUNT_ID,
        csv_content=csv_content,
    )
    created = await bank_stmt_svc.upload_statement(TENANT_A, upload_cmd)
    assert len(created) == 1
    txn_id = created[0].id
    assert created[0].amount == Decimal("1090.00")
    assert created[0].matched is False

    # 3. List unmatched
    unmatched = await reconciliation_svc.list_unmatched(TENANT_A)
    assert len(unmatched) == 1
    assert unmatched[0].id == txn_id

    # 4. Get suggestions
    suggestions = await reconciliation_svc.suggest_matches(TENANT_A, txn_id)
    assert len(suggestions) >= 1
    exact = [s for s in suggestions if s.confidence == "exact" and s.match_type == "invoice"]
    assert len(exact) >= 1
    assert exact[0].match_id == invoice_id
    assert exact[0].difference == Decimal("0")

    # 5. Reconcile (confirm match)
    reconcile_cmd = ReconcileTransactionCommand(
        transaction_id=txn_id,
        match_type="invoice",
        match_id=invoice_id,
        account_id=BANK_ACCOUNT_ID,
    )
    updated = await reconciliation_svc.confirm_match(TENANT_A, USER_ID, reconcile_cmd)

    assert updated.matched is True, f"Expected matched=True, got matched={updated.matched}"
    assert updated.journal_entry_id is not None, "Expected journal_entry_id to be set"
    assert updated.reconciliation_entity_type == "invoice"
    assert updated.reconciliation_entity_id == invoice_id

    # 6. Verify journal entry was posted correctly
    assert len(ledger.posted) == 2  # 1 from issue + 1 from reconcile
    reconcile_entry = ledger.posted[1]
    assert reconcile_entry["source_type"] == "reconciliation"
    assert reconcile_entry["source_id"] == str(txn_id)
    assert reconcile_entry["total_debit"] == Decimal("1090.00")
    assert reconcile_entry["total_credit"] == Decimal("1090.00")

    # Verify the account IDs in the journal lines: Dr Bank, Cr AR
    lines = reconcile_entry["lines"]
    assert len(lines) == 2
    bank_line = next(line for line in lines if line.debit_amount > Decimal("0"))
    ar_line = next(line for line in lines if line.credit_amount > Decimal("0"))
    assert bank_line.account_id == str(BANK_ACCOUNT_ID)
    assert ar_line.account_id == str(AR_ACCOUNT_ID)

    # 7. List matched
    matched = await reconciliation_svc.list_matched(TENANT_A)
    assert len(matched) == 1
    assert matched[0].id == txn_id
    assert matched[0].matched is True
    # 8. Verify payment was recorded for the invoice
    payment = next((pmt for pmt in payments._store.values() if pmt.invoice_id == invoice_id), None)
    assert payment is not None, "Expected a payment to be recorded for the reconciled invoice"
    assert payment.amount == Decimal("1090.00")
    assert payment.journal_entry_id == updated.journal_entry_id

    # 9. Verify invoice status was updated to PAID
    paid_invoice = await invoices.get_by_id(TENANT_A, invoice_id)
    assert paid_invoice is not None
    assert paid_invoice.status == InvoiceStatus.PAID

    # 10. Verify invoice no longer appears in suggestions (should be excluded)
    still_unmatched = await reconciliation_svc.list_unmatched(TENANT_A)
    if still_unmatched:
        # Suggestions for another unmatched txn should NOT include the paid invoice
        other_txn_id = still_unmatched[0].id
        suggestions_after = await reconciliation_svc.suggest_matches(TENANT_A, other_txn_id)
        invoice_suggestions = [
            s for s in suggestions_after if s.match_type == "invoice" and s.match_id == invoice_id
        ]
        assert len(invoice_suggestions) == 0, (
            f"Paid invoice {invoice_id} should not appear in suggestions, "
            f"but found {len(invoice_suggestions)} suggestion(s)"
        )
