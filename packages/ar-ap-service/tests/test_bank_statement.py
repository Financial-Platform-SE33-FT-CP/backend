"""US-13 bank statement CSV upload tests (service layer with in-memory fakes)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from accounting_shared.exceptions import ValidationError
from ar_ap_service.modules.ar_ap.application.bank_statement import (
    BankStatementService,
    parse_bank_statement_csv,
)
from ar_ap_service.modules.ar_ap.application.dto import UploadBankStatementCommand

from .conftest import (
    TENANT_A,
    FakeBankTransactionRepository,
)

BANK_ACCOUNT_ID = UUID("33333333-3333-3333-3333-333333333333")


# ── CSV Parser Tests ─────────────────────────────────────────────────────────────


def test_parse_simple_csv() -> None:
    csv = "date,description,amount\n2026-01-15,Payment received,1000.00\n2026-01-16,Refund,-50.00"
    txns = parse_bank_statement_csv(csv)
    assert len(txns) == 2
    assert txns[0].date == "2026-01-15"
    assert txns[0].description == "Payment received"
    assert txns[0].amount == Decimal("1000.00")
    assert txns[0].checksum_hash is not None


def test_parse_csv_with_non_standard_headers() -> None:
    csv = "Transaction Date,Narration,Amount\n15/01/2026,Invoice Payment,2500.00"
    txns = parse_bank_statement_csv(csv)
    assert len(txns) == 1
    assert txns[0].date == "2026-01-15"
    assert txns[0].amount == Decimal("2500.00")


def test_parse_csv_with_debit_credit_columns() -> None:
    csv = (
        "Date,Description,Debit,Credit\n"
        '15/01/2026,Deposit,,"1,500.00"\n'
        "16/01/2026,Withdrawal,200.00,"
    )
    txns = parse_bank_statement_csv(csv)
    assert len(txns) == 2
    assert txns[0].amount == Decimal("1500.00")  # credit
    assert txns[1].amount == Decimal("-200.00")  # debit


def test_parse_csv_date_formats() -> None:
    csv = "date,description,amount\n01/02/2026,Payment,100.00\n2026-03-15,Sale,200.00"
    txns = parse_bank_statement_csv(csv)
    assert len(txns) == 2
    assert txns[0].date == "2026-02-01"
    assert txns[1].date == "2026-03-15"


def test_parse_empty_csv_raises() -> None:
    with pytest.raises(ValidationError):
        parse_bank_statement_csv("date,description,amount")


def test_parse_csv_dedup_hash_consistency() -> None:
    csv = "date,description,amount\n2026-01-15,Payment,100.00\n2026-01-15,Payment,100.00"
    txns = parse_bank_statement_csv(csv)
    assert len(txns) == 2
    assert txns[0].checksum_hash == txns[1].checksum_hash


# ── Bank Statement Service Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_creates_transactions() -> None:
    repo = FakeBankTransactionRepository()
    service = BankStatementService(bank_txn_repo=repo)
    csv = "date,description,amount\n2026-01-15,Payment received,1000.00\n2026-01-16,Refund,-50.00"
    command = UploadBankStatementCommand(bank_account_id=BANK_ACCOUNT_ID, csv_content=csv)
    created = await service.upload_statement(TENANT_A, command)
    assert len(created) == 2
    assert created[0].bank_account_id == BANK_ACCOUNT_ID
    assert created[0].tenant_id == TENANT_A
    assert created[0].matched is False
    assert created[0].upload_batch_id is not None
    assert created[0].checksum_hash is not None


@pytest.mark.asyncio
async def test_upload_deduplicates_by_hash() -> None:
    repo = FakeBankTransactionRepository()
    service = BankStatementService(bank_txn_repo=repo)
    csv = "date,description,amount\n2026-01-15,Duplicate entry,100.00"
    command = UploadBankStatementCommand(bank_account_id=BANK_ACCOUNT_ID, csv_content=csv)
    created1 = await service.upload_statement(TENANT_A, command)
    assert len(created1) == 1
    created2 = await service.upload_statement(TENANT_A, command)
    assert len(created2) == 0  # duplicate


@pytest.mark.asyncio
async def test_upload_different_tenant_not_deduplicated() -> None:
    repo = FakeBankTransactionRepository()
    service = BankStatementService(bank_txn_repo=repo)
    csv = "date,description,amount\n2026-01-15,Same content,100.00"
    command = UploadBankStatementCommand(bank_account_id=BANK_ACCOUNT_ID, csv_content=csv)
    await service.upload_statement(TENANT_A, command)
    tenant_b = UUID("00000000-0000-0000-0000-0000000000bb")
    created = await service.upload_statement(tenant_b, command)
    assert len(created) == 1  # different tenant, not a dup


@pytest.mark.asyncio
async def test_upload_empty_batch_returns_empty() -> None:
    repo = FakeBankTransactionRepository()
    service = BankStatementService(bank_txn_repo=repo)
    csv = "date,description,amount\n2026-01-15,Existing,100.00"
    command = UploadBankStatementCommand(bank_account_id=BANK_ACCOUNT_ID, csv_content=csv)
    await service.upload_statement(TENANT_A, command)
    result = await service.upload_statement(TENANT_A, command)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_upload_invalid_csv_raises() -> None:
    repo = FakeBankTransactionRepository()
    service = BankStatementService(bank_txn_repo=repo)
    command = UploadBankStatementCommand(
        bank_account_id=BANK_ACCOUNT_ID,
        csv_content="not,enough,columns\njust one row",
    )
    with pytest.raises(ValidationError):
        await service.upload_statement(TENANT_A, command)
