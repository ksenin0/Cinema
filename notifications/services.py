"""Queue notification intent separately from delivery infrastructure."""

from accounts.models import User
from bookings.models import Order
from notifications.models import Notification


def enqueue_email(user: User | None, subject: str, body: str, order: Order | None = None) -> None:
    """Persist email intent for an active user with an address; otherwise do nothing."""
    if user and user.is_active and user.email:
        Notification.objects.create(
            user=user, recipient=user.email, subject=subject, body=body, order=order
        )
