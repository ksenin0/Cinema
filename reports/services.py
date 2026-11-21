"""Reporting read models for revenue, refunds and occupancy."""

from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum

from bookings.models import Payment
from catalog.models import Session


def build_report(start: date, end: date) -> dict:
    """Return cash movement totals and screening occupancy for an inclusive local-date range."""
    payments = Payment.objects.filter(created_at__date__range=(start, end))
    gross = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    refunds = Payment.objects.filter(refunded_at__date__range=(start, end)).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    refund_pending = Payment.objects.filter(status=Payment.Status.REFUND_PENDING).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    sessions = (
        Session.objects.filter(start_datetime__date__range=(start, end))
        .select_related("movie", "hall")
        .annotate(
            sold=Count("tickets", filter=Q(tickets__order__status="paid", tickets__is_active=True)),
            checked_in=Count(
                "tickets", filter=Q(tickets__is_checked_in=True, tickets__is_active=True)
            ),
        )
    )
    rows = []
    capacities = {}
    for session in sessions:
        if session.hall_id not in capacities:
            capacities[session.hall_id] = session.hall.seats.filter(is_available=True).count()
        capacity = capacities[session.hall_id]
        rows.append(
            {
                "session_id": session.pk,
                "movie": session.movie.title,
                "hall": session.hall.name,
                "start_datetime": session.start_datetime.isoformat(),
                "is_cancelled": session.is_cancelled,
                "capacity": capacity,
                "sold": session.sold,
                "checked_in": session.checked_in,
                "occupancy_percent": round(session.sold * 100 / capacity, 2) if capacity else 0,
            }
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "gross_revenue": f"{gross:.2f}",
        "refunds": f"{refunds:.2f}",
        "net_revenue": f"{gross - refunds:.2f}",
        "refund_pending_total": f"{refund_pending:.2f}",
        "sessions": rows,
    }
