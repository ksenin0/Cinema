"""Booking input schemas and read-only accounting output."""

from rest_framework import serializers

from bookings.models import Order, Payment, Ticket
from bookings.services import get_qr_payload


class TicketSerializer(serializers.ModelSerializer):
    """Ticket metadata; signed QR payload is exposed only for paid active tickets."""

    movie_title = serializers.CharField(source="session.movie.title", read_only=True)
    hall_name = serializers.CharField(source="session.hall.name", read_only=True)
    start_datetime = serializers.DateTimeField(source="session.start_datetime", read_only=True)
    row_number = serializers.IntegerField(source="seat.row_number", read_only=True)
    seat_number = serializers.IntegerField(source="seat.seat_number", read_only=True)
    qr_payload = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "session",
            "seat",
            "movie_title",
            "hall_name",
            "start_datetime",
            "row_number",
            "seat_number",
            "price",
            "is_active",
            "is_checked_in",
            "qr_payload",
        ]

    def get_qr_payload(self, obj: Ticket) -> str | None:
        """Return a signed identifier only if the ticket grants paid admission."""
        return (
            get_qr_payload(obj) if obj.is_active and obj.order.status == Order.Status.PAID else None
        )


class PaymentSerializer(serializers.ModelSerializer):
    """Payment information without employee or provider internals."""

    class Meta:
        model = Payment
        fields = ["id", "amount", "method", "status", "created_at", "refunded_at"]


class OrderSerializer(serializers.ModelSerializer):
    """Order and its historical ticket price snapshots."""

    tickets = TicketSerializer(many=True, read_only=True)
    payment = PaymentSerializer(read_only=True)

    class Meta:
        model = Order
        fields = ["id", "total_price", "status", "created_at", "expires_at", "tickets", "payment"]


class BookingInputSerializer(serializers.Serializer):
    """Only session/seat identifiers are accepted; prices are calculated server-side."""

    session_id = serializers.IntegerField(min_value=1)
    seat_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=20
    )


class PaymentInputSerializer(serializers.Serializer):
    """Cash/card button selection; no payment credentials are requested."""

    method = serializers.ChoiceField(choices=[Payment.Method.CASH, Payment.Method.CARD])
    reference = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CashSaleInputSerializer(BookingInputSerializer, PaymentInputSerializer):
    """Walk-in sale: seat selection and payment method."""


class CheckInSerializer(serializers.Serializer):
    """Signed QR payload scanned by a cashier."""

    payload = serializers.CharField(max_length=2048)
