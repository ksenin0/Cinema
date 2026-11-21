"""Export the same report data as CSV, XLSX and paginated PDF."""

import csv
from io import BytesIO, StringIO

from openpyxl import Workbook
from reportlab.pdfgen.canvas import Canvas

from bookings.exports import get_pdf_font

REPORT_COLUMNS = [
    "session_id",
    "movie",
    "hall",
    "start_datetime",
    "capacity",
    "sold",
    "checked_in",
    "occupancy_percent",
    "is_cancelled",
]


def safe_cell(value: object) -> object:
    """Escape spreadsheet formula prefixes in user-controlled report text."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def report_rows(report: dict) -> list[list]:
    """Return summary rows followed by the screening table, with formula-safe cells."""
    rows = [
        [key, report[key]]
        for key in (
            "start",
            "end",
            "gross_revenue",
            "refunds",
            "net_revenue",
            "refund_pending_total",
        )
    ]
    rows.extend([[], REPORT_COLUMNS])
    rows.extend(
        [[safe_cell(row[column]) for column in REPORT_COLUMNS] for row in report["sessions"]]
    )
    return rows


def export_csv(report: dict) -> bytes:
    """Return UTF-8 BOM CSV compatible with spreadsheet applications."""
    output = StringIO(newline="")
    csv.writer(output, delimiter=";").writerows(report_rows(report))
    return output.getvalue().encode("utf-8-sig")


def export_xlsx(report: dict) -> bytes:
    """Return an Excel workbook with the summary and screening occupancy table."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Cinema report"
    for row in report_rows(report):
        worksheet.append(row)
    worksheet.freeze_panes = "D9"
    for column in ("A", "B", "C", "D"):
        worksheet.column_dimensions[column].width = 30
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_pdf(report: dict) -> bytes:
    """Return a paginated text report with Unicode font support."""
    output = BytesIO()
    canvas = Canvas(output)
    font = get_pdf_font()
    canvas.setFont(font, 10)
    position = 800
    for row in report_rows(report):
        text = " | ".join(str(value) for value in row)
        for offset in range(0, max(len(text), 1), 92):
            if position < 40:
                canvas.showPage()
                canvas.setFont(font, 10)
                position = 800
            canvas.drawString(25, position, text[offset : offset + 92])
            position -= 16
    canvas.save()
    return output.getvalue()
