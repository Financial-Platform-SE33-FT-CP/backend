"""US-16 GST summary CSV export tests."""

from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO

from ar_ap_service.modules.ar_ap.application.gst_csv_export import (
    generate_gst_summary_csv,
)
from ar_ap_service.modules.ar_ap.domain.entities import GstSummary


def test_generate_gst_summary_csv() -> None:
    summary = GstSummary(
        reporting_period="2026-Q2",
        output_tax=Decimal("81.00"),
        input_tax=Decimal("45.00"),
        zero_rated_supplies=Decimal("200.00"),
        exempt_supplies=Decimal("300.00"),
    )

    csv_bytes = generate_gst_summary_csv(summary)

    # UTF-8 BOM, for Excel compatibility.
    assert csv_bytes.startswith(b"\xef\xbb\xbf")

    csv_text = csv_bytes.decode("utf-8-sig")
    rows = list(csv.reader(StringIO(csv_text)))

    assert rows == [
        [
            "reporting_period",
            "output_tax",
            "input_tax",
            "net_gst_payable",
            "zero_rated_supplies",
            "exempt_supplies",
        ],
        [
            "2026-Q2",
            "81.00",
            "45.00",
            "36.00",
            "200.00",
            "300.00",
        ],
    ]
