"""Read models for the interactive seat grid."""

from django.utils import timezone

from bookings.models import Ticket
from bookings.pricing import StandardPricePolicy
from catalog.models import Session


def get_seat_map(session: Session, user: object) -> dict:
    """Return current availability, ownership, coordinates, and computed seat prices."""
    now = timezone.now()
    allocations = {
        ticket.seat_id: ticket
        for ticket in Ticket.objects.filter(session=session, is_active=True).select_related("order")
        if ticket.order.status == "paid"
        or (ticket.order.status == "pending" and ticket.order.expires_at > now)
    }
    seats = []
    for seat in session.hall.seats.all():
        ticket = allocations.get(seat.pk)
        state, expires_at = "free", None
        if not seat.is_available or session.is_cancelled or session.start_datetime <= now:
            state = "unavailable"
        elif ticket:
            state = "occupied" if ticket.order.status == "paid" else "held"
            if state == "held":
                expires_at = ticket.order.expires_at
                if user.is_authenticated and ticket.order.user_id == user.pk:
                    state = "selected"
        seats.append(
            {
                "id": seat.pk,
                "row_number": seat.row_number,
                "seat_number": seat.seat_number,
                "seat_type": seat.seat_type,
                "status": state,
                "expires_at": expires_at,
                "price": str(StandardPricePolicy().calculate(session, seat)),
            }
        )
    return {
        "session_id": session.pk,
        "rows_count": session.hall.rows_count,
        "seats_per_row": session.hall.seats_per_row,
        "server_time": now,
        "seats": seats,
    }
