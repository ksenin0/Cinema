"""Deliver pending transactional notifications outside database write transactions."""

from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

from bookings.exports import render_ticket_pdf
from notifications.models import Notification


class Command(BaseCommand):
    """Send/retry up to 100 emails; run a single worker to avoid duplicate delivery."""

    help = "Отправить до 100 ожидающих писем (один экземпляр обработчика)."

    def handle(self, *args: object, **options: object) -> None:
        """Send queued messages, attach paid tickets, and preserve failures for retry."""
        count = 0
        for notification in Notification.objects.filter(
            sent_at__isnull=True, attempts__lt=5
        ).order_by("created_at")[:100]:
            notification.attempts += 1
            try:
                message = EmailMessage(
                    notification.subject, notification.body, to=[notification.recipient]
                )
                order = notification.order
                if order and order.status == "paid":
                    for ticket in order.tickets.select_related(
                        "session__movie", "session__hall", "seat"
                    ):
                        message.attach(
                            f"ticket-{ticket.pk}.pdf", render_ticket_pdf(ticket), "application/pdf"
                        )
                    receipt = (
                        f"Order: {order.pk}\nAmount: {order.total_price} RUB\n"
                        "Payment confirmation (not a fiscal receipt)."
                    )
                    message.attach(
                        "payment-confirmation.txt", receipt.encode("utf-8"), "text/plain"
                    )
                if message.send() != 1:
                    raise RuntimeError("Email backend did not confirm delivery.")
                notification.sent_at = timezone.now()
                notification.last_error = ""
                count += 1
            except Exception as exc:
                notification.last_error = type(exc).__name__
                self.stderr.write(f"Notification {notification.pk}: {notification.last_error}")
            notification.save(update_fields=["attempts", "sent_at", "last_error"])
        self.stdout.write(f"Отправлено: {count}")
