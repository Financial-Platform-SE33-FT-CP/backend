"""US-9 payment recording tests (service layer with in-memory fakes).

Covers the record-payment flow end to end at the service boundary: full and
partial payments, balanced journal posting, invoice status transitions,
over-allocation guards, tenant isolation, closed-period rejection and atomic
rollback when ledger posting fails.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from accounting_shared.exceptions import ConflictError, NotFoundError, ValidationError
from ar_ap_service.modules.ar_ap.application.dto import RecordPaymentCommand
from ar_ap_service.modules.ar_ap.application.services import PaymentService
from ar_ap_service.modules.ar_ap.domain.entities import (
    Customer,
    Invoice,
    InvoiceStatus,
    PaymentMethod,
)

from .conftest import (
    AR_ACCOUNT_ID,
    BANK_ACCOUNT_ID,
    TENANT_A,
    TENANT_B,
    FakeInvoiceRepository,
    FakeLedgerPoster,
    FakePaymentRepository,
)

PAY_DATE = date(2026, 6, 1)
USER_ID = uuid4()


def _seed_issued_invoice(
    invoices: FakeInvoiceRepository,
    customer_id: UUID,
    *,
    total: str = "327.00",
    tenant_id: UUID = TENANT_A,
    status: InvoiceStatus = InvoiceStatus.ISSUED,
    number: str = "INV-2026-0001",
) -> Invoice:
    invoice = Invoice(
        tenant_id=tenant_id,
        customer_id=customer_id,
        invoice_number=number,
        issue_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
        status=status,
        subtotal=Decimal(total),
        gst_amount=Decimal("0.00"),
        total=Decimal(total),
        journal_entry_id="je-invoice-1",
    )
    invoices._store[invoice.id] = invoice
    return invoice


def _command(amount: str, **kwargs) -> RecordPaymentCommand:
    return RecordPaymentCommand(
        payment_date=kwargs.pop("payment_date", PAY_DATE),
        amount=Decimal(amount),
        payment_method=kwargs.pop("payment_method", PaymentMethod.BANK_TRANSFER),
        reference=kwargs.pop("reference", "BANK-REF-001"),
        deposit_account_id=kwargs.pop("deposit_account_id", BANK_ACCOUNT_ID),
        idempotency_key=kwargs.pop("idempotency_key", None),
    )


# 1 — full payment succeeds and links a journal entry
@pytest.mark.asyncio
async def test_record_full_payment(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    payment = await payment_service.record_payment(
        TENANT_A, invoice.id, _command("327.00"), USER_ID
    )

    assert payment.amount == Decimal("327.00")
    assert payment.tenant_id == TENANT_A
    assert payment.invoice_id == invoice.id
    assert payment.customer_id == customer_a.id
    assert payment.journal_entry_id is not None
    assert payment.created_by == USER_ID


# 2 — partial payment succeeds
@pytest.mark.asyncio
async def test_record_partial_payment(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    payment = await payment_service.record_payment(
        TENANT_A, invoice.id, _command("100.00"), USER_ID
    )

    assert payment.amount == Decimal("100.00")
    assert payment.journal_entry_id is not None


# 3 — the posted journal entry is balanced
@pytest.mark.asyncio
async def test_payment_creates_balanced_journal_entry(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)

    assert len(ledger.posted) == 1
    entry = ledger.posted[0]
    assert entry["total_debit"] == entry["total_credit"] == Decimal("100.00")
    assert entry["source_id"] is not None


# 4 — debits the deposit (bank/cash) account, credits Accounts Receivable
@pytest.mark.asyncio
async def test_payment_debits_bank_credits_ar(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)

    lines = ledger.posted[0]["lines"]
    debit = next(line for line in lines if line.debit_amount > Decimal("0.00"))
    credit = next(line for line in lines if line.credit_amount > Decimal("0.00"))
    assert debit.account_id == str(BANK_ACCOUNT_ID)
    assert debit.debit_amount == Decimal("100.00")
    assert credit.account_id == str(AR_ACCOUNT_ID)
    assert credit.credit_amount == Decimal("100.00")


# 5 — issued → partial after a partial payment
@pytest.mark.asyncio
async def test_invoice_becomes_partial(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)

    refreshed = await invoices.get_by_id(TENANT_A, invoice.id)
    assert refreshed is not None
    assert refreshed.status is InvoiceStatus.PARTIAL


# 6 — issued → paid after a full payment
@pytest.mark.asyncio
async def test_invoice_becomes_paid(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    await payment_service.record_payment(TENANT_A, invoice.id, _command("327.00"), USER_ID)

    refreshed = await invoices.get_by_id(TENANT_A, invoice.id)
    assert refreshed is not None
    assert refreshed.status is InvoiceStatus.PAID


# 7 — cannot overpay
@pytest.mark.asyncio
async def test_cannot_overpay(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    with pytest.raises(ValidationError):
        await payment_service.record_payment(TENANT_A, invoice.id, _command("400.00"), USER_ID)


# 8 — cannot pay a draft invoice
@pytest.mark.asyncio
async def test_cannot_pay_draft_invoice(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(
        invoices, customer_a.id, total="327.00", status=InvoiceStatus.DRAFT, number=""
    )

    with pytest.raises(ConflictError):
        await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)


# 9 — cannot pay an already paid invoice
@pytest.mark.asyncio
async def test_cannot_pay_paid_invoice(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(
        invoices, customer_a.id, total="327.00", status=InvoiceStatus.PAID
    )

    with pytest.raises(ConflictError):
        await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)


# 11 — tenant A cannot pay tenant B's invoice
@pytest.mark.asyncio
async def test_cross_tenant_invoice_rejected(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_b: Customer,
) -> None:
    invoice = _seed_issued_invoice(
        invoices, customer_b.id, total="327.00", tenant_id=TENANT_B
    )

    with pytest.raises(NotFoundError):
        await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)


# 12 — deposit account must belong to the same tenant / be valid
@pytest.mark.asyncio
async def test_deposit_account_must_belong_to_tenant(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    with pytest.raises(ValidationError):
        await payment_service.record_payment(
            TENANT_A,
            invoice.id,
            _command("100.00", deposit_account_id=uuid4()),
            USER_ID,
        )


# 12b — deposit account must be an asset account
@pytest.mark.asyncio
async def test_deposit_account_must_be_asset(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    from .conftest import REVENUE_ACCOUNT_ID

    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    with pytest.raises(ValidationError):
        await payment_service.record_payment(
            TENANT_A,
            invoice.id,
            _command("100.00", deposit_account_id=REVENUE_ACCOUNT_ID),
            USER_ID,
        )


# 13 — cannot post a payment into a closed accounting period
@pytest.mark.asyncio
async def test_cannot_pay_in_closed_period(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")
    ledger.closed_dates.add(PAY_DATE)

    with pytest.raises(ConflictError):
        await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)


# 14 — failed ledger posting saves no payment and leaves invoice status unchanged
@pytest.mark.asyncio
async def test_failed_journal_posting_is_atomic(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    payments: FakePaymentRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")
    ledger.fail_with = RuntimeError("ledger down")

    with pytest.raises(RuntimeError):
        await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)

    assert payments._store == {}
    refreshed = await invoices.get_by_id(TENANT_A, invoice.id)
    assert refreshed is not None
    assert refreshed.status is InvoiceStatus.ISSUED


# 15 — listing invoice payments is tenant-scoped
@pytest.mark.asyncio
async def test_list_invoice_payments_tenant_scoped(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")
    await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)

    own = await payment_service.list_invoice_payments(TENANT_A, invoice.id)
    assert len(own) == 1

    # A different tenant cannot even see the invoice, let alone its payments.
    with pytest.raises(NotFoundError):
        await payment_service.list_invoice_payments(TENANT_B, invoice.id)


# 16 — multiple partial payments accumulate and finalize the invoice
@pytest.mark.asyncio
async def test_multiple_partial_payments_sum(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    await payment_service.record_payment(TENANT_A, invoice.id, _command("100.00"), USER_ID)
    await payment_service.record_payment(TENANT_A, invoice.id, _command("200.00"), USER_ID)

    settlement = await payment_service.get_invoice_settlement(TENANT_A, invoice.id)
    assert settlement.amount_paid == Decimal("300.00")
    assert settlement.outstanding == Decimal("27.00")

    # Final payment clears the balance and marks the invoice paid.
    await payment_service.record_payment(TENANT_A, invoice.id, _command("27.00"), USER_ID)
    refreshed = await invoices.get_by_id(TENANT_A, invoice.id)
    assert refreshed is not None
    assert refreshed.status is InvoiceStatus.PAID


# 16b — a partial payment cannot be followed by one that exceeds the remainder
@pytest.mark.asyncio
async def test_partial_then_overpay_rejected(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")
    await payment_service.record_payment(TENANT_A, invoice.id, _command("300.00"), USER_ID)

    with pytest.raises(ValidationError):
        await payment_service.record_payment(TENANT_A, invoice.id, _command("50.00"), USER_ID)


# 17 — outstanding balance reflects posted payments
@pytest.mark.asyncio
async def test_outstanding_balance_calculation(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    before = await payment_service.get_invoice_settlement(TENANT_A, invoice.id)
    assert before.outstanding == Decimal("327.00")

    await payment_service.record_payment(TENANT_A, invoice.id, _command("127.00"), USER_ID)

    after = await payment_service.get_invoice_settlement(TENANT_A, invoice.id)
    assert after.amount_paid == Decimal("127.00")
    assert after.outstanding == Decimal("200.00")


# 18 — zero/negative amounts are rejected by the command schema
@pytest.mark.asyncio
async def test_zero_amount_rejected() -> None:
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        _command("0.00")


# 19 — idempotency: a repeated key returns the original payment, no double-post
@pytest.mark.asyncio
async def test_idempotent_retry_returns_same_payment(
    payment_service: PaymentService,
    invoices: FakeInvoiceRepository,
    payments: FakePaymentRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    first = await payment_service.record_payment(
        TENANT_A, invoice.id, _command("100.00", idempotency_key="abc-123"), USER_ID
    )
    second = await payment_service.record_payment(
        TENANT_A, invoice.id, _command("100.00", idempotency_key="abc-123"), USER_ID
    )

    assert first.id == second.id
    assert len(payments._store) == 1
    assert len(ledger.posted) == 1
