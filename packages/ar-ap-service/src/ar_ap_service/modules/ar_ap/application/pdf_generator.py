"""Generate customer invoice PDFs (US-8)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ar_ap_service.modules.ar_ap.domain.entities import Customer, Invoice, InvoiceLine

_ZERO = Decimal("0.00")


def _money(value: Decimal | str | float | int) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return f"${amount:,.2f}"


def _format_date(value: date | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d %b %Y")


def _format_status(status: str) -> str:
    return status.replace("_", " ").title()


def generate_invoice_pdf(
    invoice: Invoice,
    customer: Customer | None,
    *,
    company_name: str = "Accounting Platform",
) -> bytes:
    """Build a printable PDF for an issued invoice."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=invoice.invoice_number or "Invoice",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontSize=20,
        spaceAfter=6,
    )
    muted = ParagraphStyle(
        "Muted",
        parent=styles["Normal"],
        textColor=colors.HexColor("#555555"),
        fontSize=9,
    )
    right = ParagraphStyle(
        "Right",
        parent=styles["Normal"],
        alignment=TA_RIGHT,
    )

    story: list[object] = []
    story.append(Paragraph(company_name, styles["Heading3"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("TAX INVOICE", title_style))
    story.append(
        Paragraph(
            f"<b>{invoice.invoice_number or 'Draft'}</b> · {_format_status(invoice.status.value)}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 6 * mm))

    meta_rows = [
        ["Bill to", "Invoice details"],
        [
            Paragraph(
                "<br/>".join(
                    filter(
                        None,
                        [
                            f"<b>{customer.name}</b>" if customer else "<b>Customer</b>",
                            customer.email if customer and customer.email else "",
                        ],
                    )
                ),
                styles["Normal"],
            ),
            Paragraph(
                "<br/>".join(
                    [
                        f"Issue date: <b>{_format_date(invoice.issue_date)}</b>",
                        f"Due date: <b>{_format_date(invoice.due_date)}</b>",
                        (
                            "Created: "
                            + (
                                _format_date(invoice.created_at.date())
                                if isinstance(invoice.created_at, datetime)
                                else "?"
                            )
                        ),
                    ]
                ),
                styles["Normal"],
            ),
        ],
    ]
    meta_table = Table(meta_rows, colWidths=[90 * mm, 80 * mm])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(meta_table)
    story.append(Spacer(1, 8 * mm))

    line_header = [
        "Description",
        "Qty",
        "Unit price",
        "GST %",
        "Subtotal",
        "GST",
        "Total",
    ]
    line_rows: list[list[str | Paragraph]] = [line_header]
    for line in invoice.lines:
        line_rows.append(_line_row(line, styles["Normal"], right))

    lines_table = Table(
        line_rows,
        colWidths=[58 * mm, 14 * mm, 22 * mm, 16 * mm, 22 * mm, 18 * mm, 22 * mm],
        repeatRows=1,
    )
    lines_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(lines_table)
    story.append(Spacer(1, 6 * mm))

    totals = Table(
        [
            ["Subtotal", _money(invoice.subtotal)],
            ["GST", _money(invoice.gst_amount)],
            ["Total", _money(invoice.total)],
        ],
        colWidths=[140 * mm, 32 * mm],
    )
    totals.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(totals)
    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            "This document was generated electronically and is valid without a signature.",
            muted,
        )
    )

    doc.build(story)
    return buffer.getvalue()


def _line_row(
    line: InvoiceLine,
    normal: ParagraphStyle,
    right_style: ParagraphStyle,
) -> list[str | Paragraph]:
    rate = Decimal(str(line.gst_rate or _ZERO)) * Decimal("100")
    gross = Decimal(str(line.line_total)) + Decimal(str(line.gst_amount))
    return [
        Paragraph(line.description or "—", normal),
        Paragraph(str(line.quantity), right_style),
        Paragraph(_money(line.unit_price), right_style),
        Paragraph(f"{rate:.2f}%", right_style),
        Paragraph(_money(line.line_total), right_style),
        Paragraph(_money(line.gst_amount), right_style),
        Paragraph(_money(gross), right_style),
    ]
