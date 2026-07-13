"""Generate CSV exports for GST reporting summaries."""

from __future__ import annotations

import csv
from io import StringIO

from ar_ap_service.modules.ar_ap.domain.entities import GstSummary


def _format_amount(value: object) -> str:
    """Format a monetary value using exactly two decimal places."""
    return f"{value:.2f}"


def generate_gst_summary_csv(summary: GstSummary) -> bytes:
    """Generate a UTF-8 CSV export for one GST reporting period.

    The UTF-8 BOM improves compatibility when the file is opened directly
    using Microsoft Excel.
    """
    output = StringIO(newline="")

    writer = csv.writer(
        output,
        lineterminator="\n",
    )

    writer.writerow(
        [
            "reporting_period",
            "output_tax",
            "input_tax",
            "net_gst_payable",
            "zero_rated_supplies",
            "exempt_supplies",
        ]
    )

    writer.writerow(
        [
            summary.reporting_period,
            _format_amount(summary.output_tax),
            _format_amount(summary.input_tax),
            _format_amount(summary.net_gst_payable),
            _format_amount(summary.zero_rated_supplies),
            _format_amount(summary.exempt_supplies),
        ]
    )

    return output.getvalue().encode("utf-8-sig")
