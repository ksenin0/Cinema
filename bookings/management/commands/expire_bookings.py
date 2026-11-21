"""Periodic command for releasing expired holds without incoming API traffic."""

from django.core.management.base import BaseCommand

from bookings.services import expire_orders


class Command(BaseCommand):
    """Release expired ten-minute holds; suitable for Windows Task Scheduler."""

    help = "Освободить неоплаченные брони с истекшим сроком."

    def handle(self, *args: object, **options: object) -> None:
        """Run one expiration pass and print the count of expired orders."""
        self.stdout.write(f"Истекло броней: {expire_orders()}")
