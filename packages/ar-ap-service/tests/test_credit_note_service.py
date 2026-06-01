"""US-10 credit note tests (service layer with in-memory fakes).

Covers issuing credit notes against issued invoices end to end at the service
boundary: full and partial credit notes, the balanced reversal journal entry
(Debit Revenue, Debit GST Output, Credit Accounts Receivable), GST adjustment,
credit-note numbering, invoice linkage, creditable-amount limits, draft/tenant
guards, closed-period rejection, atomic rollback and immutability of the original
invoice journal entry.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from accounting_shared.exceptions import ConflictError, NotFoundError, ValidationError
from ar_ap_service.modules.ar_ap.application.dto import (
    CreditNoteLineInput,
    IssueCreditNoteCommand,
)
from ar_ap_service.modules.ar_ap.application.services import CreditNoteService
from ar_ap_service.modules.ar_ap.domain.entities import (
    Customer,
    Invoice,
    InvoiceStatus,
)

from .conftest import (
    AR_ACCOUNT_ID,
    EXPENSE_ACCOUNT_ID,
    GST_ACCOUNT_ID,
    REVENUE_ACCOUNT_ID,
    TENANT_A,
    TENANT_B,
    FakeCreditNoteRepository,
    FakeInvoiceRepository,
    FakeLedgerPoster,
)

ISSUE_DATE = date(2026, 6, 1)
USER_ID = uuid4()


def _seed_issued_invoice(
    invoices: FakeInvoiceRepository,
    customer_id: UUID,
    *,
    total: str = "327.00",
    gst: str = "27.00",
    subtotal: str = "300.00",
    tenant_id: UUID = TENANT_A,
    status: InvoiceStatus = InvoiceStatus.ISSUED,
    number: str = "INV-2026-0001",
    journal_entry_id: str = "je-invoice-1",
) -> Invoice:
    invoice = Invoice(
        tenant_id=tenant_id,
        customer_id=customer_id,
        invoice_number=number,
        issue_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
        status=status,
        subtotal=Decimal(subtotal),
        gst_amount=Decimal(gst),
        total=Decimal(total),
        journal_entry_id=journal_entry_id,
    )
    invoices._store[invoice.id] = invoice
    return invoice


def _line(
    unit_price: str,
    *,
    quantity: str = "1",
    gst_rate: str = "0.09",
    account_id: UUID = REVENUE_ACCOUNT_ID,
    invoice_line_id: UUID | None = None,
) -> CreditNoteLineInput:
    return CreditNoteLineInput(
        account_id=account_id,
        quantity=Decimal(quantity),
        unit_price=Decimal(unit_price),
        description="Credit for consulting service",
        gst_rate=Decimal(gst_rate),
        invoice_line_id=invoice_line_id,
    )


def _command(*lines: CreditNoteLineInput, **kwargs) -> IssueCreditNoteCommand:
    return IssueCreditNoteCommand(
        issue_date=kwargs.pop("issue_date", ISSUE_DATE),
        reason=kwargs.pop("reason", "Invoice correction"),
        lines=list(lines) or [_line("300.00")],
        idempotency_key=kwargs.pop("idempotency_key", None),
    )


# 1 — issue a full credit note successfully
@pytest.mark.asyncio
async def test_issue_full_credit_note(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    credit_note = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("300.00")), USER_ID
    )

    assert credit_note.subtotal == Decimal("300.00")
    assert credit_note.gst_amount == Decimal("27.00")
    assert credit_note.total == Decimal("327.00")
    assert credit_note.tenant_id == TENANT_A
    assert credit_note.customer_id == customer_a.id
    assert credit_note.journal_entry_id is not None
    assert credit_note.created_by == USER_ID


# 2 — issue a partial credit note successfully
@pytest.mark.asyncio
async def test_issue_partial_credit_note(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    credit_note = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
    )

    assert credit_note.subtotal == Decimal("100.00")
    assert credit_note.gst_amount == Decimal("9.00")
    assert credit_note.total == Decimal("109.00")


# 3 — the posted journal entry is balanced
@pytest.mark.asyncio
async def test_credit_note_creates_balanced_journal_entry(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("300.00")), USER_ID
    )

    assert len(ledger.posted) == 1
    entry = ledger.posted[0]
    assert entry["total_debit"] == entry["total_credit"] == Decimal("327.00")
    assert entry["source_type"] == "credit_note"
    assert entry["is_reversal"] is True
    assert entry["reversed_entry_id"] == "je-invoice-1"


# 4 — debits Revenue and GST Output, credits Accounts Receivable
@pytest.mark.asyncio
async def test_credit_note_debits_revenue_gst_credits_ar(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("300.00")), USER_ID
    )

    lines = ledger.posted[0]["lines"]
    by_account = {line.account_id: line for line in lines}

    revenue = by_account[str(REVENUE_ACCOUNT_ID)]
    assert revenue.debit_amount == Decimal("300.00")
    assert revenue.credit_amount == Decimal("0.00")

    gst = by_account[str(GST_ACCOUNT_ID)]
    assert gst.debit_amount == Decimal("27.00")
    assert gst.credit_amount == Decimal("0.00")

    ar = by_account[str(AR_ACCOUNT_ID)]
    assert ar.credit_amount == Decimal("327.00")
    assert ar.debit_amount == Decimal("0.00")


# 5 — GST is calculated by the backend (not trusted from the client)
@pytest.mark.asyncio
async def test_gst_amount_calculated_by_backend(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    credit_note = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00", quantity="2")), USER_ID
    )

    # net 200, GST 9% = 18, total 218
    assert credit_note.subtotal == Decimal("200.00")
    assert credit_note.gst_amount == Decimal("18.00")
    assert credit_note.total == Decimal("218.00")


# 6 — credit note number is generated and increments per tenant/year
@pytest.mark.asyncio
async def test_credit_note_number_generated(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="654.00")

    first = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
    )
    second = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
    )

    assert first.credit_note_number == "CN-2026-0001"
    assert second.credit_note_number == "CN-2026-0002"


# 7 — the credit note is linked to the original invoice
@pytest.mark.asyncio
async def test_credit_note_linked_to_invoice(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    credit_note = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
    )

    assert credit_note.invoice_id == invoice.id


# 8 — cannot issue a credit note for a draft invoice
@pytest.mark.asyncio
async def test_cannot_credit_draft_invoice(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(
        invoices, customer_a.id, status=InvoiceStatus.DRAFT, number="", journal_entry_id=""
    )

    with pytest.raises(ConflictError):
        await credit_note_service.issue_credit_note(
            TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
        )


# 9 — cannot issue a credit note exceeding the invoice total
@pytest.mark.asyncio
async def test_cannot_exceed_invoice_total(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    with pytest.raises(ValidationError):
        await credit_note_service.issue_credit_note(
            TENANT_A, invoice.id, _command(_line("400.00")), USER_ID
        )


# 10 — cannot exceed the remaining creditable amount after previous credit notes
@pytest.mark.asyncio
async def test_cannot_exceed_remaining_creditable(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, total="327.00")

    # First credit note for 218 (net 200 + GST 18) leaves 109 creditable.
    await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00", quantity="2")), USER_ID
    )

    # A second 218 credit note would push the total past the invoice value.
    with pytest.raises(ValidationError):
        await credit_note_service.issue_credit_note(
            TENANT_A, invoice.id, _command(_line("100.00", quantity="2")), USER_ID
        )

    # But the remaining 109 is allowed.
    remaining = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
    )
    assert remaining.total == Decimal("109.00")


# 12 — tenant A cannot credit tenant B's invoice
@pytest.mark.asyncio
async def test_cross_tenant_invoice_rejected(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_b: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_b.id, tenant_id=TENANT_B)

    with pytest.raises(NotFoundError):
        await credit_note_service.issue_credit_note(
            TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
        )


# 13 — revenue account must belong to the same tenant
@pytest.mark.asyncio
async def test_revenue_account_must_belong_to_tenant(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    with pytest.raises(ValidationError):
        await credit_note_service.issue_credit_note(
            TENANT_A,
            invoice.id,
            _command(_line("100.00", account_id=uuid4())),
            USER_ID,
        )


# 13b — credit note lines must post to a revenue account
@pytest.mark.asyncio
async def test_line_account_must_be_revenue(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    with pytest.raises(ValidationError):
        await credit_note_service.issue_credit_note(
            TENANT_A,
            invoice.id,
            _command(_line("100.00", account_id=EXPENSE_ACCOUNT_ID)),
            USER_ID,
        )


# 14 — cannot post a credit note into a closed accounting period
@pytest.mark.asyncio
async def test_cannot_credit_in_closed_period(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)
    ledger.closed_dates.add(ISSUE_DATE)

    with pytest.raises(ConflictError):
        await credit_note_service.issue_credit_note(
            TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
        )


# 15 — failed ledger posting saves no credit note (atomic)
@pytest.mark.asyncio
async def test_failed_journal_posting_is_atomic(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    credit_notes: FakeCreditNoteRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)
    ledger.fail_with = RuntimeError("ledger down")

    with pytest.raises(RuntimeError):
        await credit_note_service.issue_credit_note(
            TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
        )

    assert credit_notes._store == {}


# 16 — listing invoice credit notes is tenant-scoped
@pytest.mark.asyncio
async def test_list_invoice_credit_notes_tenant_scoped(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)
    await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
    )

    own = await credit_note_service.list_invoice_credit_notes(TENANT_A, invoice.id)
    assert len(own) == 1

    # A different tenant cannot even see the invoice, let alone its credit notes.
    with pytest.raises(NotFoundError):
        await credit_note_service.list_invoice_credit_notes(TENANT_B, invoice.id)


# 17 — the original invoice and its journal entry are not mutated
@pytest.mark.asyncio
async def test_original_invoice_journal_entry_not_mutated(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("300.00")), USER_ID
    )

    refreshed = await invoices.get_by_id(TENANT_A, invoice.id)
    assert refreshed is not None
    assert refreshed.status is InvoiceStatus.ISSUED
    assert refreshed.journal_entry_id == "je-invoice-1"


# 18 — issuing against a fully paid invoice is still allowed (MVP scope)
@pytest.mark.asyncio
async def test_credit_note_allowed_on_paid_invoice(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    customer_a: Customer,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id, status=InvoiceStatus.PAID)

    credit_note = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00")), USER_ID
    )
    assert credit_note.total == Decimal("109.00")


# 19 — idempotency: a repeated key returns the original credit note, no double-post
@pytest.mark.asyncio
async def test_idempotent_retry_returns_same_credit_note(
    credit_note_service: CreditNoteService,
    invoices: FakeInvoiceRepository,
    credit_notes: FakeCreditNoteRepository,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
) -> None:
    invoice = _seed_issued_invoice(invoices, customer_a.id)

    first = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00"), idempotency_key="cn-abc-123"), USER_ID
    )
    second = await credit_note_service.issue_credit_note(
        TENANT_A, invoice.id, _command(_line("100.00"), idempotency_key="cn-abc-123"), USER_ID
    )

    assert first.id == second.id
    assert len(credit_notes._store) == 1
    assert len(ledger.posted) == 1
