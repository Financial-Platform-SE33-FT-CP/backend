"""US-8 invoice lifecycle tests (service layer with in-memory fakes)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from accounting_shared.exceptions import ConflictError, NotFoundError, ValidationError
from ar_ap_service.modules.ar_ap.application.dto import (
    CreateInvoiceCommand,
    InvoiceLineInput,
    UpdateInvoiceCommand,
)
from ar_ap_service.modules.ar_ap.application.services import InvoiceService
from ar_ap_service.modules.ar_ap.domain.entities import Customer, InvoiceStatus

from .conftest import (
    AR_ACCOUNT_ID,
    EXPENSE_ACCOUNT_ID,
    GST_ACCOUNT_ID,
    REVENUE_ACCOUNT_2_ID,
    REVENUE_ACCOUNT_ID,
    TENANT_A,
    TENANT_B,
    FakeInvoiceRepository,
    FakeLedgerPoster,
)

ISSUE_DATE = date(2026, 3, 1)
DUE_DATE = date(2026, 3, 31)
USER_ID = uuid4()


def _command(
    customer_id, *, gst_rate="0.09", quantity="10", unit_price="100"
) -> CreateInvoiceCommand:
    return CreateInvoiceCommand(
        customer_id=customer_id,
        issue_date=ISSUE_DATE,
        due_date=DUE_DATE,
        lines=[
            InvoiceLineInput(
                account_id=REVENUE_ACCOUNT_ID,
                quantity=Decimal(quantity),
                unit_price=Decimal(unit_price),
                description="Consulting",
                gst_rate=Decimal(gst_rate),
            )
        ],
    )


# 1 — create draft successfully
@pytest.mark.asyncio
async def test_create_draft_invoice(service: InvoiceService, customer_a: Customer) -> None:
    invoice = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    assert invoice.status is InvoiceStatus.DRAFT
    assert invoice.tenant_id == TENANT_A
    assert invoice.created_by == USER_ID
    assert invoice.invoice_number == ""  # number only assigned on issue
    assert invoice.subtotal == Decimal("1000.00")
    assert invoice.gst_amount == Decimal("90.00")
    assert invoice.total == Decimal("1090.00")


# 2 — draft does not create a journal entry
@pytest.mark.asyncio
async def test_draft_does_not_post_to_ledger(
    service: InvoiceService, customer_a: Customer, ledger: FakeLedgerPoster
) -> None:
    invoice = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    assert invoice.journal_entry_id is None
    assert ledger.posted == []


# 3 + 6 — issue creates a journal entry and assigns an invoice number
@pytest.mark.asyncio
async def test_issue_creates_journal_entry_and_number(
    service: InvoiceService, customer_a: Customer, ledger: FakeLedgerPoster
) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    issued = await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    assert issued.status is InvoiceStatus.ISSUED
    assert issued.journal_entry_id is not None
    assert issued.invoice_number == "INV-2026-0001"
    assert len(ledger.posted) == 1
    assert ledger.posted[0]["source_id"] == str(draft.id)


# 4 — journal entry is balanced with correct debit/credit legs
@pytest.mark.asyncio
async def test_issue_journal_entry_is_balanced(
    service: InvoiceService, customer_a: Customer, ledger: FakeLedgerPoster
) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)
    await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    entry = ledger.posted[0]
    assert entry["total_debit"] == entry["total_credit"] == Decimal("1090.00")

    legs = {str(line.account_id): line for line in entry["lines"]}
    assert legs[str(AR_ACCOUNT_ID)].debit_amount == Decimal("1090.00")
    assert legs[str(REVENUE_ACCOUNT_ID)].credit_amount == Decimal("1000.00")
    assert legs[str(GST_ACCOUNT_ID)].credit_amount == Decimal("90.00")


# 5 — GST is computed correctly; no GST line when rate is zero
@pytest.mark.asyncio
async def test_zero_gst_has_no_gst_leg(
    service: InvoiceService, customer_a: Customer, ledger: FakeLedgerPoster
) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id, gst_rate="0"), USER_ID)
    issued = await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    assert issued.gst_amount == Decimal("0.00")
    assert issued.total == Decimal("1000.00")
    leg_accounts = {str(line.account_id) for line in ledger.posted[0]["lines"]}
    assert str(GST_ACCOUNT_ID) not in leg_accounts


@pytest.mark.asyncio
async def test_multiple_revenue_accounts_grouped(
    service: InvoiceService, customer_a: Customer, ledger: FakeLedgerPoster
) -> None:
    command = CreateInvoiceCommand(
        customer_id=customer_a.id,
        issue_date=ISSUE_DATE,
        due_date=DUE_DATE,
        lines=[
            InvoiceLineInput(
                account_id=REVENUE_ACCOUNT_ID,
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                gst_rate=Decimal("0.09"),
            ),
            InvoiceLineInput(
                account_id=REVENUE_ACCOUNT_2_ID,
                quantity=Decimal("2"),
                unit_price=Decimal("50"),
                gst_rate=Decimal("0.09"),
            ),
        ],
    )
    draft = await service.create_draft(TENANT_A, command, USER_ID)
    issued = await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    assert issued.subtotal == Decimal("200.00")
    assert issued.gst_amount == Decimal("18.00")
    legs = {str(line.account_id): line for line in ledger.posted[0]["lines"]}
    assert legs[str(REVENUE_ACCOUNT_ID)].credit_amount == Decimal("100.00")
    assert legs[str(REVENUE_ACCOUNT_2_ID)].credit_amount == Decimal("100.00")


# 7 — an issued invoice cannot be edited
@pytest.mark.asyncio
async def test_issued_invoice_cannot_be_edited(
    service: InvoiceService, customer_a: Customer
) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)
    await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    with pytest.raises(ConflictError, match="draft"):
        await service.update_draft(
            TENANT_A, draft.id, UpdateInvoiceCommand(due_date=date(2026, 4, 30))
        )


@pytest.mark.asyncio
async def test_issued_invoice_cannot_be_deleted(
    service: InvoiceService, customer_a: Customer
) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)
    await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    with pytest.raises(ConflictError):
        await service.delete_draft(TENANT_A, draft.id)


# 9 — tenant isolation
@pytest.mark.asyncio
async def test_tenant_cannot_access_other_tenant_invoice(
    service: InvoiceService, customer_a: Customer
) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    with pytest.raises(NotFoundError):
        await service.get_invoice(TENANT_B, draft.id)
    with pytest.raises(NotFoundError):
        await service.issue_invoice(TENANT_B, draft.id, USER_ID)


@pytest.mark.asyncio
async def test_list_is_scoped_to_tenant(
    service: InvoiceService, customer_a: Customer, customer_b: Customer
) -> None:
    await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)
    await service.create_draft(TENANT_B, _command(customer_b.id), USER_ID)

    assert len(await service.list_invoices(TENANT_A)) == 1
    assert len(await service.list_invoices(TENANT_B)) == 1


# 10 — cannot issue into a closed period; invoice stays draft
@pytest.mark.asyncio
async def test_cannot_issue_into_closed_period(
    service: InvoiceService,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
    invoices: FakeInvoiceRepository,
) -> None:
    ledger.closed_dates.add(ISSUE_DATE)
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    with pytest.raises(ConflictError, match="closed"):
        await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    still = await invoices.get_by_id(TENANT_A, draft.id)
    assert still is not None
    assert still.status is InvoiceStatus.DRAFT
    assert still.journal_entry_id is None


# 11 — cannot issue the same invoice twice
@pytest.mark.asyncio
async def test_cannot_issue_twice(service: InvoiceService, customer_a: Customer) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)
    await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    with pytest.raises(ConflictError, match="already been issued"):
        await service.issue_invoice(TENANT_A, draft.id, USER_ID)


# 12 — if journal posting fails, invoice remains draft
@pytest.mark.asyncio
async def test_failed_posting_leaves_invoice_draft(
    service: InvoiceService,
    customer_a: Customer,
    ledger: FakeLedgerPoster,
    invoices: FakeInvoiceRepository,
) -> None:
    ledger.fail_with = RuntimeError("ledger exploded")
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    with pytest.raises(RuntimeError):
        await service.issue_invoice(TENANT_A, draft.id, USER_ID)

    still = await invoices.get_by_id(TENANT_A, draft.id)
    assert still is not None
    assert still.status is InvoiceStatus.DRAFT
    assert still.journal_entry_id is None


# validation rules
@pytest.mark.asyncio
async def test_due_date_before_issue_date_rejected(
    service: InvoiceService, customer_a: Customer
) -> None:
    command = CreateInvoiceCommand(
        customer_id=customer_a.id,
        issue_date=DUE_DATE,
        due_date=ISSUE_DATE,
        lines=[
            InvoiceLineInput(
                account_id=REVENUE_ACCOUNT_ID,
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
            )
        ],
    )
    with pytest.raises(ValidationError, match="due_date"):
        await service.create_draft(TENANT_A, command, USER_ID)


@pytest.mark.asyncio
async def test_non_revenue_account_rejected(service: InvoiceService, customer_a: Customer) -> None:
    command = CreateInvoiceCommand(
        customer_id=customer_a.id,
        issue_date=ISSUE_DATE,
        due_date=DUE_DATE,
        lines=[
            InvoiceLineInput(
                account_id=EXPENSE_ACCOUNT_ID,
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
            )
        ],
    )
    with pytest.raises(ValidationError, match="revenue"):
        await service.create_draft(TENANT_A, command, USER_ID)


@pytest.mark.asyncio
async def test_unknown_customer_rejected(service: InvoiceService) -> None:
    with pytest.raises(ValidationError, match="Customer"):
        await service.create_draft(TENANT_A, _command(uuid4()), USER_ID)


@pytest.mark.asyncio
async def test_update_recomputes_totals(service: InvoiceService, customer_a: Customer) -> None:
    draft = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    updated = await service.update_draft(
        TENANT_A,
        draft.id,
        UpdateInvoiceCommand(
            lines=[
                InvoiceLineInput(
                    account_id=REVENUE_ACCOUNT_ID,
                    quantity=Decimal("2"),
                    unit_price=Decimal("100"),
                    gst_rate=Decimal("0.09"),
                )
            ]
        ),
    )

    assert updated.subtotal == Decimal("200.00")
    assert updated.gst_amount == Decimal("18.00")
    assert updated.total == Decimal("218.00")


@pytest.mark.asyncio
async def test_invoice_numbers_increment(service: InvoiceService, customer_a: Customer) -> None:
    first = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)
    second = await service.create_draft(TENANT_A, _command(customer_a.id), USER_ID)

    issued_first = await service.issue_invoice(TENANT_A, first.id, USER_ID)
    issued_second = await service.issue_invoice(TENANT_A, second.id, USER_ID)

    assert issued_first.invoice_number == "INV-2026-0001"
    assert issued_second.invoice_number == "INV-2026-0002"
