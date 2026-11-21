"""Portable electronic ticket rendering, independent of API response handling."""

from io import BytesIO
from pathlib import Path

import qrcode
from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from bookings.models import Ticket
from bookings.services import get_qr_payload


def get_pdf_font() -> str:
    """Register a Unicode font once; fall back to Helvetica for ASCII-only deployments."""
    if (
        "Cinema" not in pdfmetrics.getRegisteredFontNames()
        and Path(settings.PDF_FONT_PATH).exists()
    ):
        pdfmetrics.registerFont(TTFont("Cinema", settings.PDF_FONT_PATH))
    return "Cinema" if "Cinema" in pdfmetrics.getRegisteredFontNames() else "Helvetica"


def ticket_lines(ticket: Ticket) -> list[str]:
    """Return ticket details without exposing customer personal data."""
    return [
        ticket.session.movie.title,
        f"Зал: {ticket.session.hall.name}",
        f"Сеанс: {timezone.localtime(ticket.session.start_datetime):%d.%m.%Y %H:%M}",
        f"Ряд: {ticket.seat.row_number}   Место: {ticket.seat.seat_number}",
        f"Цена: {ticket.price} RUB",
        f"Заказ: {ticket.order_id}",
    ]


def render_qr_png(ticket: Ticket) -> bytes:
    """Return a valid PNG containing the signed QR payload."""
    buffer = BytesIO()
    qrcode.make(get_qr_payload(ticket)).save(buffer, format="PNG")
    return buffer.getvalue()


def render_ticket_png(ticket: Ticket) -> bytes:
    """Render the ticket details and its scannable QR as a single PNG image."""
    canvas = Image.new("RGB", (1000, 1000), "white")
    draw = ImageDraw.Draw(canvas)
    font = (
        ImageFont.truetype(settings.PDF_FONT_PATH, 26)
        if Path(settings.PDF_FONT_PATH).exists()
        else ImageFont.load_default(size=24)
    )
    for index, line in enumerate(ticket_lines(ticket)):
        # Wrap unusually long titles to keep all information within the ticket canvas.
        chunks = [line[offset : offset + 55] for offset in range(0, len(line), 55)]
        for chunk_index, chunk in enumerate(chunks):
            draw.text((30, 25 + index * 66 + chunk_index * 30), chunk, fill="black", font=font)
    qr_image = Image.open(BytesIO(render_qr_png(ticket)))
    qr_image.thumbnail((550, 550), Image.Resampling.NEAREST)
    canvas.paste(qr_image, ((1000 - qr_image.width) // 2, 440))
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def render_ticket_pdf(ticket: Ticket) -> bytes:
    """Return an A4 PDF with full ticket data and a signed scannable QR code."""
    buffer = BytesIO()
    canvas = Canvas(buffer)
    canvas.setFont(get_pdf_font(), 12)
    line_position = 790
    for line in ticket_lines(ticket):
        for offset in range(0, len(line), 65):
            canvas.drawString(35, line_position, line[offset : offset + 65])
            line_position -= 22
    canvas.drawImage(ImageReader(BytesIO(render_qr_png(ticket))), 125, 120, 340, 340)
    canvas.save()
    return buffer.getvalue()
