"""US-11 bill recording tests (service layer with in-memory fakes)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from accounting_shared.exceptions import ConflictError, NotFoundError, ValidationError
from ar_ap_service.modules.ar_ap.application.dto import BillLineInput, CreateBillCommand
from ar_ap_service.modules.ar_ap.application.services import BillService
from ar_ap_service.modules.ar_ap.domain.entities import Bill, BillStatus, Vendor

from .conftest import (
    AP_ACCOUNT_ID,
    EXPENSE_ACCOUNT_ID,
    GST_INPUT_ACCOUNT_ID,
    TENANT_A,
    TENANT_B,
    FakeBillRepository,
    FakeLedgerPoster,
    FakeVendorRepository,
)

BILL_DATE = date(2026, 4, 1)
DUE_DATE = date(2026, 4, 30)
USER_ID = uuid4()


def _line(**kwargs) -> BillLineInput:
    return BillLineInput(
        account_id=kwargs.pop("account_id", EXPENSE_ACCOUNT_ID),
        quantity=kwargs.pop("quantity", Decimal("1")),
        unit_price=kwargs.pop("unit_price", Decimal("100")),
        description=kwargs.pop("description", "Office supplies"),
        gst_rate=kwargs.pop("gst_rate", Decimal("0.09")),
    )


def _create_command(vendor_id: UUID, *, gst_rate: Decimal = Decimal("0.09")) -> CreateBillCommand:
    return CreateBillCommand(
        vendor_id=vendor_id,
        issue_date=BILL_DATE,
        due_date=DUE_DATE,
        lines=[_line(gst_rate=gst_rate)],
    )


@pytest.mark.asyncio
async def test_create_draft_bill(
    bill_service: BillService,
    vendor_a: Vendor,
) -> None:
    bill = await bill_service.create_draft(TENANT_A, _create_command(vendor_a.id), USER_ID)
    assert bill.status == BillStatus.DRAFT
    assert bill.total == Decimal("109.00")
    assert bill.gst_amount == Decimal("9.00")
    assert bill.subtotal == Decimal("100.00")


@pytest.mark.asyncio
async def test_create_bill_without_gst(
    bill_service: BillService,
    vendor_a: Vendor,
) -> None:
    bill = await bill_service.create_draft(
        TENANT_A, _create_command(vendor_a.id, gst_rate=Decimal("0")), USER_ID
    )
    assert bill.gst_amount == Decimal("0.00")
    assert bill.total == Decimal("100.00")


@pytest.mark.asyncio
async def test_record_bill_posts_balanced_journal(
    bill_service: BillService,
    vendor_a: Vendor,
    ledger: FakeLedgerPoster,
) -> None:
    draft = await bill_service.create_draft(TENANT_A, _create_command(vendor_a.id), USER_ID)
    recorded = await bill_service.record_bill(TENANT_A, draft.id, USER_ID)

    assert recorded.status == BillStatus.OPEN
    assert recorded.bill_number.startswith("BILL-2026-")
    assert recorded.journal_entry_id is not None
    assert len(ledger.posted) == 1
    entry = ledger.posted[0]
    assert entry["total_debit"] == entry["total_credit"] == Decimal("109.00")
    assert entry["source_type"] == "bill"


@pytest.mark.asyncio
async def test_record_bill_debits_expense_gst_credits_ap(
    bill_service: BillService,
    vendor_a: Vendor,
    ledger: FakeLedgerPoster,
) -> None:
    draft = await bill_service.create_draft(TENANT_A, _create_command(vendor_a.id), USER_ID)
    await bill_service.record_bill(TENANT_A, draft.id, USER_ID)

    lines = ledger.posted[0]["lines"]
    expense = next(line for line in lines if line.account_id == str(EXPENSE_ACCOUNT_ID))
    gst = next(line for line in lines if line.account_id == str(GST_INPUT_ACCOUNT_ID))
    ap = next(line for line in lines if line.account_id == str(AP_ACCOUNT_ID))
    assert expense.debit_amount == Decimal("100.00")
    assert gst.debit_amount == Decimal("9.00")
    assert ap.credit_amount == Decimal("109.00")


@pytest.mark.asyncio
async def test_cannot_record_bill_twice(
    bill_service: BillService,
    vendor_a: Vendor,
) -> None:
    draft = await bill_service.create_draft(TENANT_A, _create_command(vendor_a.id), USER_ID)
    await bill_service.record_bill(TENANT_A, draft.id, USER_ID)
    with pytest.raises(ConflictError, match="already been recorded"):
        await bill_service.record_bill(TENANT_A, draft.id, USER_ID)


@pytest.mark.asyncio
async def test_missing_vendor_rejected(
    bill_service: BillService,
) -> None:
    with pytest.raises(ValidationError, match="Vendor not found"):
        await bill_service.create_draft(TENANT_A, _create_command(uuid4()), USER_ID)


@pytest.mark.asyncio
async def test_tenant_isolation_on_get(
    bill_service: BillService,
    bills: FakeBillRepository,
    vendor_a: Vendor,
) -> None:
    bill = Bill(
        tenant_id=TENANT_A,
        vendor_id=vendor_a.id,
        bill_number="BILL-2026-0001",
        issue_date=BILL_DATE,
        due_date=DUE_DATE,
        status=BillStatus.OPEN,
        total=Decimal("100.00"),
    )
    bills._store[bill.id] = bill
    with pytest.raises(NotFoundError):
        await bill_service.get_bill(TENANT_B, bill.id)
