"""US-15/US-16 GST reporting service tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from ar_ap_service.modules.ar_ap.application.services import GstService
from ar_ap_service.modules.ar_ap.domain.entities import (
    GstKind,
    GstSourceType,
    GstTransaction,
)

from .conftest import (
    GST_EXEMPT_CODE_ID,
    GST_INPUT_CODE_ID,
    GST_OUTPUT_CODE_ID,
    GST_ZERO_RATED_CODE_ID,
    TENANT_A,
    FakeGstRepository,
)


@pytest.mark.asyncio
async def test_get_summary_aggregates_gst_transactions(
    gst: FakeGstRepository,
) -> None:
    service = GstService(gst=gst)

    transactions = [
        GstTransaction(
            tenant_id=TENANT_A,
            source_type=GstSourceType.INVOICE,
            source_id=uuid4(),
            gst_code_id=GST_OUTPUT_CODE_ID,
            taxable_amount=Decimal("1000.00"),
            gst_amount=Decimal("90.00"),
            reporting_period="2026-Q2",
            transaction_date=date(2026, 4, 10),
        ),
        GstTransaction(
            tenant_id=TENANT_A,
            source_type=GstSourceType.CREDIT_NOTE,
            source_id=uuid4(),
            gst_code_id=GST_OUTPUT_CODE_ID,
            taxable_amount=Decimal("-100.00"),
            gst_amount=Decimal("-9.00"),
            reporting_period="2026-Q2",
            transaction_date=date(2026, 4, 20),
        ),
        GstTransaction(
            tenant_id=TENANT_A,
            source_type=GstSourceType.BILL,
            source_id=uuid4(),
            gst_code_id=GST_INPUT_CODE_ID,
            taxable_amount=Decimal("500.00"),
            gst_amount=Decimal("45.00"),
            reporting_period="2026-Q2",
            transaction_date=date(2026, 5, 5),
        ),
        GstTransaction(
            tenant_id=TENANT_A,
            source_type=GstSourceType.INVOICE,
            source_id=uuid4(),
            gst_code_id=GST_ZERO_RATED_CODE_ID,
            taxable_amount=Decimal("200.00"),
            gst_amount=Decimal("0.00"),
            reporting_period="2026-Q2",
            transaction_date=date(2026, 5, 15),
        ),
        GstTransaction(
            tenant_id=TENANT_A,
            source_type=GstSourceType.INVOICE,
            source_id=uuid4(),
            gst_code_id=GST_EXEMPT_CODE_ID,
            taxable_amount=Decimal("300.00"),
            gst_amount=Decimal("0.00"),
            reporting_period="2026-Q2",
            transaction_date=date(2026, 6, 1),
        ),
    ]

    await gst.add_transactions(transactions)

    summary = await service.get_summary(
        TENANT_A,
        "2026-Q2",
    )

    assert summary.reporting_period == "2026-Q2"
    assert summary.output_tax == Decimal("81.00")
    assert summary.input_tax == Decimal("45.00")
    assert summary.net_gst_payable == Decimal("36.00")
    assert summary.zero_rated_supplies == Decimal("200.00")
    assert summary.exempt_supplies == Decimal("300.00")


@pytest.mark.asyncio
async def test_ensure_default_codes_creates_codes_idempotently() -> None:
    gst = FakeGstRepository()
    service = GstService(gst=gst)

    first_result = await service.ensure_default_codes(TENANT_A)
    second_result = await service.ensure_default_codes(TENANT_A)

    assert len(first_result) == 4
    assert len(second_result) == 4

    observed = {
        (
            code.code,
            code.rate,
            code.gst_kind,
            code.is_active,
        )
        for code in second_result
    }

    assert observed == {
        (
            "SR-OUTPUT",
            Decimal("0.09"),
            GstKind.OUTPUT,
            True,
        ),
        (
            "SR-INPUT",
            Decimal("0.09"),
            GstKind.INPUT,
            True,
        ),
        (
            "ZERO",
            Decimal("0.00"),
            GstKind.ZERO_RATED,
            True,
        ),
        (
            "EXEMPT",
            Decimal("0.00"),
            GstKind.EXEMPT,
            True,
        ),
    }

    stored_codes = await gst.list_codes(
        TENANT_A,
        active_only=False,
    )

    assert len(stored_codes) == 4
