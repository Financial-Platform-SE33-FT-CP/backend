"""US-8 invoice PDF generation tests."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from ar_ap_service.modules.ar_ap.application.pdf_generator import generate_invoice_pdf
from ar_ap_service.modules.ar_ap.domain.entities import (
    Customer,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
)


def _issued_invoice() -> Invoice:
    invoice_id = uuid4()
    return Invoice(
        id=invoice_id,
        tenant_id=uuid4(),
        customer_id=uuid4(),
        invoice_number="INV-2026-0001",
        issue_date=date(2026, 3, 1),
        due_date=date(2026, 3, 31),
        status=InvoiceStatus.ISSUED,
        subtotal=Decimal("1000.00"),
        gst_amount=Decimal("90.00"),
        total=Decimal("1090.00"),
        journal_entry_id=str(uuid4()),
        created_at=datetime(2026, 3, 1, 10, 0, 0),
        lines=[
            InvoiceLine(
                account_id=uuid4(),
                quantity=Decimal("10"),
                unit_price=Decimal("100"),
                description="Consulting services",
                gst_rate=Decimal("0.09"),
                invoice_id=invoice_id,
                line_total=Decimal("1000.00"),
                gst_amount=Decimal("90.00"),
            )
        ],
    )


def test_generate_invoice_pdf_returns_pdf_bytes() -> None:
    customer = Customer(id=uuid4(), tenant_id=uuid4(), name="Acme Pte Ltd", email="billing@acme.sg")
    pdf = generate_invoice_pdf(_issued_invoice(), customer)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500


def test_generate_invoice_pdf_without_customer() -> None:
    pdf = generate_invoice_pdf(_issued_invoice(), None)

    assert pdf.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_build_invoice_pdf_rejects_draft(service, customer_a) -> None:
    from accounting_shared.exceptions import ValidationError
    from ar_ap_service.modules.ar_ap.application.dto import CreateInvoiceCommand, InvoiceLineInput

    from .conftest import REVENUE_ACCOUNT_ID, TENANT_A

    invoice = await service.create_draft(
        TENANT_A,
        CreateInvoiceCommand(
            customer_id=customer_a.id,
            issue_date=date(2026, 3, 1),
            due_date=date(2026, 3, 31),
            lines=[
                InvoiceLineInput(
                    account_id=REVENUE_ACCOUNT_ID,
                    quantity=Decimal("1"),
                    unit_price=Decimal("100"),
                    gst_rate=Decimal("0.09"),
                )
            ],
        ),
        uuid4(),
    )

    with pytest.raises(ValidationError, match="issued invoices"):
        await service.build_invoice_pdf(TENANT_A, invoice.id)


@pytest.mark.asyncio
async def test_build_invoice_pdf_for_issued_invoice(service, customer_a) -> None:
    from ar_ap_service.modules.ar_ap.application.dto import CreateInvoiceCommand, InvoiceLineInput

    from .conftest import GST_OUTPUT_CODE_ID, REVENUE_ACCOUNT_ID, TENANT_A

    draft = await service.create_draft(
        TENANT_A,
        CreateInvoiceCommand(
            customer_id=customer_a.id,
            issue_date=date(2026, 3, 1),
            due_date=date(2026, 3, 31),
            lines=[
                InvoiceLineInput(
                    account_id=REVENUE_ACCOUNT_ID,
                    quantity=Decimal("1"),
                    unit_price=Decimal("100"),
                    gst_code_id=GST_OUTPUT_CODE_ID,
                    gst_rate=Decimal("0.09"),
                )
            ],
        ),
        uuid4(),
    )
    issued = await service.issue_invoice(TENANT_A, draft.id, uuid4())

    pdf_bytes, filename = await service.build_invoice_pdf(TENANT_A, issued.id)

    assert pdf_bytes.startswith(b"%PDF")
    assert filename == "INV-2026-0001.pdf"
