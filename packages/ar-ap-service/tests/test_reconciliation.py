"""US-14 bank transaction reconciliation tests (service layer with in-memory fakes)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from ar_ap_service.modules.ar_ap.domain.entities import BankTransaction

from accounting_shared.exceptions import NotFoundError, ValidationError
from ar_ap_service.modules.ar_ap.application.dto import (
    CreateInvoiceCommand,
    InvoiceLineInput,
    ReconcileTransactionCommand,
)
from .conftest import (
    AR_ACCOUNT_ID,
    BANK_ACCOUNT_ID,
    REVENUE_ACCOUNT_ID,
    TENANT_A,
    FakeBankTransactionRepository,
    FakeLedgerPoster,
)

ISSUE_DATE = date(2026, 3, 1)
DUE_DATE = date(2026, 3, 31)
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _seed_unmatched_txn(
    repo: FakeBankTransactionRepository,
    *,
    amount: Decimal = Decimal("1000.00"),
    matched: bool = False,
) -> BankTransaction:
    txn = BankTransaction(
        id=uuid4(),
        tenant_id=TENANT_A,
        bank_account_id=BANK_ACCOUNT_ID,
        transaction_date=date(2026, 3, 15),
        description="Test transaction",
        amount=amount,
        matched=matched,
        checksum_hash="abc123",
        created_at=datetime.utcnow(),
    )
    repo._store[txn.id] = txn
    return txn


# ── List Unmatched / Matched ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_unmatched_returns_only_unmatched(
    reconciliation_service, bank_transactions: FakeBankTransactionRepository
) -> None:
    _seed_unmatched_txn(bank_transactions, amount=Decimal("500.00"))
    _seed_unmatched_txn(
        bank_transactions,
        amount=Decimal("200.00"),
        matched=True,
    )
    unmatched = await reconciliation_service.list_unmatched(TENANT_A)
    assert len(unmatched) == 1
    assert unmatched[0].amount == Decimal("500.00")


@pytest.mark.asyncio
async def test_list_matched_returns_only_matched(
    reconciliation_service, bank_transactions: FakeBankTransactionRepository
) -> None:
    _seed_unmatched_txn(bank_transactions, amount=Decimal("500.00"))
    _seed_unmatched_txn(
        bank_transactions,
        amount=Decimal("200.00"),
        matched=True,
    )
    matched = await reconciliation_service.list_matched(TENANT_A)
    assert len(matched) == 1
    assert matched[0].amount == Decimal("200.00")


@pytest.mark.asyncio
async def test_list_unmatched_filters_by_account(
    reconciliation_service, bank_transactions: FakeBankTransactionRepository
) -> None:
    _seed_unmatched_txn(bank_transactions, amount=Decimal("100.00"))
    other_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    txn = _seed_unmatched_txn(bank_transactions, amount=Decimal("200.00"))
    txn.bank_account_id = other_id

    result = await reconciliation_service.list_unmatched(TENANT_A, bank_account_id=BANK_ACCOUNT_ID)
    assert len(result) == 1
    assert result[0].amount == Decimal("100.00")


# ── Suggest Matches ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suggest_matches_finds_exact_invoice_match(
    reconciliation_service,
    bank_transactions: FakeBankTransactionRepository,
    service: InvoiceService,
    customer_a,
    accounts,
    ledger: FakeLedgerPoster,
) -> None:
    txn = _seed_unmatched_txn(bank_transactions, amount=Decimal("1090.00"))

    # Create and issue an invoice with total=1090.00
    from ar_ap_service.modules.ar_ap.application.dto import (
        CreateInvoiceCommand,
        InvoiceLineInput,
    )
    cmd = CreateInvoiceCommand(
        customer_id=customer_a.id,
        issue_date=ISSUE_DATE,
        due_date=DUE_DATE,
        lines=[
            InvoiceLineInput(
                account_id=REVENUE_ACCOUNT_ID,
                quantity=Decimal("10"),
                unit_price=Decimal("100"),
                description="Service",
                gst_rate=Decimal("0.09"),
            )
        ],
    )
    draft = await service.create_draft(TENANT_A, cmd, USER_ID)
    await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    suggestions = await reconciliation_service.suggest_matches(TENANT_A, txn.id)
    exact = [s for s in suggestions if s.confidence == "exact"]
    assert len(exact) >= 1


@pytest.mark.asyncio
async def test_suggest_matches_not_found_raises(
    reconciliation_service,
) -> None:
    with pytest.raises(NotFoundError):
        await reconciliation_service.suggest_matches(
            TENANT_A,
            UUID("00000000-0000-0000-0000-000000000999"),
        )


@pytest.mark.asyncio
async def test_suggest_matches_already_matched_raises(
    reconciliation_service,
    bank_transactions: FakeBankTransactionRepository,
) -> None:
    txn = _seed_unmatched_txn(bank_transactions, matched=True)
    with pytest.raises(ValidationError):
        await reconciliation_service.suggest_matches(TENANT_A, txn.id)


# ── Confirm Match ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_match_posts_journal_entry(
    reconciliation_service,
    bank_transactions: FakeBankTransactionRepository,
    ledger: FakeLedgerPoster,
) -> None:
    txn = _seed_unmatched_txn(bank_transactions, amount=Decimal("1500.00"))
    cmd = ReconcileTransactionCommand(
        transaction_id=txn.id,
        match_type="other",
        account_id=AR_ACCOUNT_ID,
    )
    updated = await reconciliation_service.confirm_match(TENANT_A, USER_ID, cmd)

    assert updated.matched is True
    assert updated.journal_entry_id is not None
    assert len(ledger.posted) == 1
    entry = ledger.posted[0]
    assert entry["source_type"] == "reconciliation"
    assert entry["source_id"] == str(txn.id)
    assert entry["total_debit"] == Decimal("1500.00")
    assert entry["total_credit"] == Decimal("1500.00")


@pytest.mark.asyncio
async def test_confirm_match_not_found_raises(
    reconciliation_service,
) -> None:
    cmd = ReconcileTransactionCommand(
        transaction_id=UUID("00000000-0000-0000-0000-000000000999"),
        match_type="other",
        account_id=AR_ACCOUNT_ID,
    )
    with pytest.raises(NotFoundError):
        await reconciliation_service.confirm_match(TENANT_A, USER_ID, cmd)


@pytest.mark.asyncio
async def test_confirm_match_already_matched_raises(
    reconciliation_service,
    bank_transactions: FakeBankTransactionRepository,
) -> None:
    txn = _seed_unmatched_txn(bank_transactions, matched=True)
    cmd = ReconcileTransactionCommand(
        transaction_id=txn.id,
        match_type="other",
        account_id=AR_ACCOUNT_ID,
    )
    with pytest.raises(ValidationError):
        await reconciliation_service.confirm_match(TENANT_A, USER_ID, cmd)


@pytest.mark.asyncio
async def test_confirm_match_withdrawal_posts_correct_journal(
    reconciliation_service,
    bank_transactions: FakeBankTransactionRepository,
    ledger: FakeLedgerPoster,
) -> None:
    txn = _seed_unmatched_txn(bank_transactions, amount=Decimal("-500.00"))
    cmd = ReconcileTransactionCommand(
        transaction_id=txn.id,
        match_type="other",
        account_id=AR_ACCOUNT_ID,
    )
    updated = await reconciliation_service.confirm_match(TENANT_A, USER_ID, cmd)

    assert updated.matched is True
    assert len(ledger.posted) == 1
    entry = ledger.posted[0]
    # withdrawal: Cr Bank, Dr Other
    lines = entry["lines"]
    credit_lines = [l for l in lines if l.credit_amount > Decimal("0")]
    debit_lines = [l for l in lines if l.debit_amount > Decimal("0")]
    assert len(credit_lines) == 1
    assert len(debit_lines) == 1
    assert credit_lines[0].credit_amount == Decimal("500.00")
    assert debit_lines[0].debit_amount == Decimal("500.00")


@pytest.mark.asyncio
async def test_confirm_match_updates_reconciliation_fields(
    reconciliation_service,
    bank_transactions: FakeBankTransactionRepository,
) -> None:
    txn = _seed_unmatched_txn(bank_transactions, amount=Decimal("750.00"))
    match_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    cmd = ReconcileTransactionCommand(
        transaction_id=txn.id,
        match_type="invoice",
        match_id=match_id,
        account_id=AR_ACCOUNT_ID,
    )
    updated = await reconciliation_service.confirm_match(TENANT_A, USER_ID, cmd)

    assert updated.reconciliation_entity_type == "invoice"
    assert updated.reconciliation_entity_id == match_id
