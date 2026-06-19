"""US-12 bill payment tests (service layer with in-memory fakes)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from accounting_shared.exceptions import ConflictError, ValidationError
from ar_ap_service.modules.ar_ap.application.dto import PayBillCommand
from ar_ap_service.modules.ar_ap.application.services import BillPaymentService
from ar_ap_service.modules.ar_ap.domain.entities import Bill, BillStatus, PaymentMethod, Vendor

from .conftest import (
    AP_ACCOUNT_ID,
    BANK_ACCOUNT_ID,
    TENANT_A,
    FakeBillPaymentRepository,
    FakeBillRepository,
    FakeLedgerPoster,
)

PAY_DATE = date(2026, 5, 1)
USER_ID = uuid4()


def _seed_open_bill(
    bills: FakeBillRepository,
    vendor_id: UUID,
    *,
    total: str = "109.00",
    due_date: date = date(2026, 4, 30),
) -> Bill:
    bill = Bill(
        tenant_id=TENANT_A,
        vendor_id=vendor_id,
        bill_number="BILL-2026-0001",
        issue_date=date(2026, 4, 1),
        due_date=due_date,
        status=BillStatus.OPEN,
        subtotal=Decimal("100.00"),
        gst_amount=Decimal("9.00"),
        total=Decimal(total),
        journal_entry_id="je-bill-1",
    )
    bills._store[bill.id] = bill
    return bill


def _command(amount: str, **kwargs) -> PayBillCommand:
    return PayBillCommand(
        payment_date=kwargs.pop("payment_date", PAY_DATE),
        amount=Decimal(amount),
        payment_method=kwargs.pop("payment_method", PaymentMethod.BANK_TRANSFER),
        reference=kwargs.pop("reference", "BANK-REF-001"),
        payment_account_id=kwargs.pop("payment_account_id", BANK_ACCOUNT_ID),
        idempotency_key=kwargs.pop("idempotency_key", None),
    )


@pytest.mark.asyncio
async def test_pay_bill_partial(
    bill_payment_service: BillPaymentService,
    bills: FakeBillRepository,
    vendor_a: Vendor,
) -> None:
    bill = _seed_open_bill(bills, vendor_a.id)
    payment = await bill_payment_service.pay_bill(
        TENANT_A, bill.id, _command("50.00"), USER_ID
    )
    assert payment.amount == Decimal("50.00")
    updated = bills._store[bill.id]
    assert updated.status == BillStatus.PARTIAL


@pytest.mark.asyncio
async def test_pay_bill_full(
    bill_payment_service: BillPaymentService,
    bills: FakeBillRepository,
    vendor_a: Vendor,
) -> None:
    bill = _seed_open_bill(bills, vendor_a.id)
    await bill_payment_service.pay_bill(TENANT_A, bill.id, _command("109.00"), USER_ID)
    assert bills._store[bill.id].status == BillStatus.PAID


@pytest.mark.asyncio
async def test_overpayment_rejected(
    bill_payment_service: BillPaymentService,
    bills: FakeBillRepository,
    vendor_a: Vendor,
) -> None:
    bill = _seed_open_bill(bills, vendor_a.id)
    with pytest.raises(ValidationError, match="exceeds the outstanding balance"):
        await bill_payment_service.pay_bill(TENANT_A, bill.id, _command("200.00"), USER_ID)


@pytest.mark.asyncio
async def test_payment_journal_debits_ap_credits_bank(
    bill_payment_service: BillPaymentService,
    bills: FakeBillRepository,
    vendor_a: Vendor,
    ledger: FakeLedgerPoster,
) -> None:
    bill = _seed_open_bill(bills, vendor_a.id)
    await bill_payment_service.pay_bill(TENANT_A, bill.id, _command("50.00"), USER_ID)

    lines = ledger.posted[0]["lines"]
    debit = next(line for line in lines if line.debit_amount > Decimal("0.00"))
    credit = next(line for line in lines if line.credit_amount > Decimal("0.00"))
    assert debit.account_id == str(AP_ACCOUNT_ID)
    assert credit.account_id == str(BANK_ACCOUNT_ID)


@pytest.mark.asyncio
async def test_ap_aging_reflects_outstanding(
    bill_payment_service: BillPaymentService,
    bills: FakeBillRepository,
    bill_payments: FakeBillPaymentRepository,
    vendor_a: Vendor,
) -> None:
    bill = _seed_open_bill(bills, vendor_a.id, due_date=date(2026, 3, 1))
    await bill_payment_service.pay_bill(TENANT_A, bill.id, _command("9.00"), USER_ID)

    aging = await bill_payment_service.get_ap_aging(TENANT_A, as_of=date(2026, 5, 1))
    assert len(aging) == 1
    row = aging[0]
    assert row.outstanding == Decimal("100.00")
    assert row.aging_bucket == "61-90"


@pytest.mark.asyncio
async def test_cannot_pay_draft_bill(
    bill_payment_service: BillPaymentService,
    bills: FakeBillRepository,
    vendor_a: Vendor,
) -> None:
    bill = Bill(
        tenant_id=TENANT_A,
        vendor_id=vendor_a.id,
        status=BillStatus.DRAFT,
        total=Decimal("100.00"),
    )
    bills._store[bill.id] = bill
    with pytest.raises(ConflictError, match="draft bill"):
        await bill_payment_service.pay_bill(TENANT_A, bill.id, _command("50.00"), USER_ID)
