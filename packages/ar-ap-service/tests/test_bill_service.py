"""Bill recording and GST integration tests for the merged Epic 7 service."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from accounting_shared.exceptions import ConflictError, NotFoundError, ValidationError
from ar_ap_service.modules.ar_ap.application.bill_service import BillService
from ar_ap_service.modules.ar_ap.domain.entities import Bill, BillStatus, GstSourceType, Vendor

from .conftest import (
    AP_ACCOUNT_ID,
    EXPENSE_ACCOUNT_ID,
    GST_INPUT_ACCOUNT_ID,
    GST_INPUT_CODE_ID,
    GST_OUTPUT_CODE_ID,
    TENANT_A,
    TENANT_B,
    FakeBillRepository,
    FakeGstRepository,
    FakeLedgerPoster,
)

BILL_DATE = date(2026, 4, 1)
DUE_DATE = date(2026, 4, 30)
USER_ID = uuid4()


def _line(**overrides: object) -> dict[str, object]:
    gst_rate = Decimal(str(overrides.pop("gst_rate", Decimal("0.09"))))
    gst_code_id = overrides.pop(
        "gst_code_id",
        GST_INPUT_CODE_ID if gst_rate > Decimal("0") else None,
    )
    return {
        "account_id": overrides.pop("account_id", EXPENSE_ACCOUNT_ID),
        "quantity": overrides.pop("quantity", Decimal("1")),
        "unit_price": overrides.pop("unit_price", Decimal("100")),
        "description": overrides.pop("description", "Office supplies"),
        "gst_code_id": gst_code_id,
        "gst_rate": gst_rate,
        **overrides,
    }


async def _create_draft(
    bill_service: BillService,
    vendor_id: UUID,
    *,
    gst_rate: Decimal = Decimal("0.09"),
) -> Bill:
    return await bill_service.create_draft(
        TENANT_A,
        vendor_id,
        issue_date=BILL_DATE,
        due_date=DUE_DATE,
        lines_input=[_line(gst_rate=gst_rate)],
        created_by=USER_ID,
    )


@pytest.mark.asyncio
async def test_create_draft_bill(
    bill_service: BillService,
    vendor_a: Vendor,
) -> None:
    bill = await _create_draft(bill_service, vendor_a.id)

    assert bill.status == BillStatus.DRAFT
    assert bill.subtotal == Decimal("100.00")
    assert bill.gst_amount == Decimal("9.00")
    assert bill.total == Decimal("109.00")
    assert bill.lines[0].gst_code_id == GST_INPUT_CODE_ID


@pytest.mark.asyncio
async def test_create_bill_without_gst(
    bill_service: BillService,
    vendor_a: Vendor,
) -> None:
    bill = await _create_draft(
        bill_service,
        vendor_a.id,
        gst_rate=Decimal("0"),
    )

    assert bill.gst_amount == Decimal("0.00")
    assert bill.total == Decimal("100.00")


@pytest.mark.asyncio
async def test_record_bill_posts_balanced_journal(
    bill_service: BillService,
    vendor_a: Vendor,
    ledger: FakeLedgerPoster,
) -> None:
    draft = await _create_draft(bill_service, vendor_a.id)
    recorded = await bill_service.record_bill(TENANT_A, draft.id, USER_ID)

    assert recorded.status == BillStatus.OPEN
    assert recorded.bill_number.startswith("BILL-")
    assert recorded.journal_entry_id is not None
    assert len(ledger.posted) == 1

    entry = ledger.posted[0]
    assert entry["total_debit"] == entry["total_credit"] == Decimal("109.00")
    assert entry["source_type"] == "bill"


@pytest.mark.asyncio
async def test_record_bill_debits_expense_gst_and_credits_ap(
    bill_service: BillService,
    vendor_a: Vendor,
    ledger: FakeLedgerPoster,
) -> None:
    draft = await _create_draft(bill_service, vendor_a.id)
    await bill_service.record_bill(TENANT_A, draft.id, USER_ID)

    lines = ledger.posted[0]["lines"]
    expense = next(line for line in lines if line.account_id == str(EXPENSE_ACCOUNT_ID))
    gst_line = next(line for line in lines if line.account_id == str(GST_INPUT_ACCOUNT_ID))
    ap = next(line for line in lines if line.account_id == str(AP_ACCOUNT_ID))

    assert expense.debit_amount == Decimal("100.00")
    assert gst_line.debit_amount == Decimal("9.00")
    assert ap.credit_amount == Decimal("109.00")


@pytest.mark.asyncio
async def test_record_bill_records_input_gst_transaction(
    bill_service: BillService,
    vendor_a: Vendor,
    gst: FakeGstRepository,
) -> None:
    draft = await _create_draft(bill_service, vendor_a.id)
    recorded = await bill_service.record_bill(TENANT_A, draft.id, USER_ID)

    transactions = await gst.list_transactions_by_period(TENANT_A, "2026-Q2")

    assert len(transactions) == 1
    transaction = transactions[0]
    assert transaction.tenant_id == TENANT_A
    assert transaction.source_type is GstSourceType.BILL
    assert transaction.source_id == recorded.id
    assert transaction.gst_code_id == GST_INPUT_CODE_ID
    assert transaction.taxable_amount == Decimal("100.00")
    assert transaction.gst_amount == Decimal("9.00")
    assert transaction.reporting_period == "2026-Q2"
    assert transaction.transaction_date == BILL_DATE


@pytest.mark.asyncio
async def test_cannot_record_bill_twice(
    bill_service: BillService,
    vendor_a: Vendor,
) -> None:
    draft = await _create_draft(bill_service, vendor_a.id)
    await bill_service.record_bill(TENANT_A, draft.id, USER_ID)

    with pytest.raises(ConflictError, match="already recorded"):
        await bill_service.record_bill(TENANT_A, draft.id, USER_ID)


@pytest.mark.asyncio
async def test_missing_vendor_rejected(
    bill_service: BillService,
) -> None:
    with pytest.raises(ValidationError, match="Vendor not found"):
        await bill_service.create_draft(
            TENANT_A,
            uuid4(),
            issue_date=BILL_DATE,
            due_date=DUE_DATE,
            lines_input=[_line()],
            created_by=USER_ID,
        )


@pytest.mark.asyncio
async def test_output_gst_code_rejected_for_bill(
    bill_service: BillService,
    vendor_a: Vendor,
) -> None:
    with pytest.raises(ValidationError, match="cannot be used on a bill"):
        await bill_service.create_draft(
            TENANT_A,
            vendor_a.id,
            issue_date=BILL_DATE,
            due_date=DUE_DATE,
            lines_input=[
                _line(
                    gst_code_id=GST_OUTPUT_CODE_ID,
                    gst_rate=Decimal("0.09"),
                )
            ],
            created_by=USER_ID,
        )


@pytest.mark.asyncio
async def test_tenant_isolation_on_get(
    bill_service: BillService,
    bills: FakeBillRepository,
    vendor_a: Vendor,
) -> None:
    bill = Bill(
        tenant_id=TENANT_A,
        vendor_id=vendor_a.id,
        bill_number="BILL-0001",
        issue_date=BILL_DATE,
        due_date=DUE_DATE,
        status=BillStatus.OPEN,
        total=Decimal("100.00"),
    )
    bills._store[bill.id] = bill

    with pytest.raises(NotFoundError):
        await bill_service.get_bill(TENANT_B, bill.id)
