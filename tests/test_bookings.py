"""Booking state transitions, payment accounting, QR validation, and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings.models import Order, Payment, Ticket
from bookings.selectors import get_seat_map
from bookings.services import (
    cancel_order,
    cancel_session,
    check_in_ticket,
    confirm_refund,
    create_booking,
    create_cash_sale,
    expire_orders,
    get_qr_payload,
    record_payment,
)
from catalog.models import Hall, Seat
from common.exceptions import Conflict
from reports.services import build_report
from tests.factories import TEST_STORAGES, create_catalog, create_user


@override_settings(
    STORAGES=TEST_STORAGES, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class BookingTests(TestCase):
    """Core financial and allocation invariants."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create two customers, personnel, and a future screening."""
        cls.movie, cls.hall, cls.session = create_catalog()
        cls.user = create_user()
        cls.other = create_user("other")
        cls.cashier = create_user("cashier", "cashier")
        cls.seat = cls.hall.seats.first()

    def test_vip_pricing_is_a_snapshot(self) -> None:
        """Later category edits affect future purchases, preserving existing order totals."""
        self.seat.seat_type = Seat.Type.VIP
        self.seat.save()
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        self.assertEqual(order.total_price, Decimal("450.00"))
        self.seat.seat_type = Seat.Type.STANDARD
        self.seat.save()
        order.refresh_from_db()
        self.assertEqual(order.total_price, Decimal("450.00"))

    def test_duplicate_and_foreign_hall_selections_fail(self) -> None:
        """Invalid selections never leave partially created orders."""
        hall = Hall.objects.create(name="Other", rows_count=1, seats_per_row=1)
        for selection in ([], [self.seat.pk, self.seat.pk], [hall.seats.first().pk]):
            with self.assertRaises(ValidationError):
                create_booking(self.user, self.session.pk, selection)
        self.assertEqual(Order.objects.count(), 0)

    def test_large_valid_prices_fit_order_and_ticket_fields(self) -> None:
        """Accepted base prices and multipliers remain serializable without overflow."""
        from bookings.serializers import OrderSerializer

        self.hall.vip_multiplier = Decimal("99.99")
        self.hall.save()
        self.session.base_price = Decimal("99999999.99")
        self.session.save()
        self.seat.seat_type = Seat.Type.VIP
        self.seat.save()
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        data = OrderSerializer(order).data
        self.assertEqual(data["total_price"], "9998999999.00")

    def test_same_place_cannot_be_reserved_twice(self) -> None:
        """A second customer cannot reserve an allocated seat."""
        create_booking(self.user, self.session.pk, [self.seat.pk])
        with self.assertRaises(Conflict):
            create_booking(self.other, self.session.pk, [self.seat.pk])
        self.assertEqual(Ticket.objects.filter(is_active=True).count(), 1)

    def test_expired_hold_is_free_without_worker_and_rebookable(self) -> None:
        """Availability is time-aware; a new booking cleans expired allocations atomically."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        matrix = get_seat_map(self.session, AnonymousUser())
        self.assertEqual(matrix["seats"][0]["status"], "free")
        create_booking(self.other, self.session.pk, [self.seat.pk])
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.EXPIRED)
        self.assertFalse(order.tickets.first().is_active)

    def test_expiration_command_does_not_release_paid_tickets(self) -> None:
        """A paid order keeps its allocated seat after the original hold deadline."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        record_payment(order.pk, "cash", self.cashier)
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(expire_orders(), 0)
        self.assertTrue(order.tickets.first().is_active)

    def test_payment_is_idempotent_and_rejects_changed_references(self) -> None:
        """Retries create exactly one payment record and one purchase notification."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        record_payment(order.pk, "card", self.cashier, "terminal-1")
        record_payment(order.pk, "card", self.cashier, "terminal-1")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(self.user.notification_set.count(), 1)
        with self.assertRaises(Conflict):
            record_payment(order.pk, "cash", self.cashier)

    def test_expired_payment_is_rejected(self) -> None:
        """An expired hold cannot be converted into a paid order."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(Conflict):
            record_payment(order.pk, "cash", self.cashier)
        self.assertEqual(Payment.objects.count(), 0)

    def test_failed_cash_sale_rolls_back_its_allocations(self) -> None:
        """Payment validation failure rolls back both tickets and the walk-in order."""
        with self.assertRaises(ValidationError):
            create_cash_sale(self.cashier, self.session.pk, [self.seat.pk], "online")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_session_cancellation_requires_real_refund_confirmation(self) -> None:
        """Cancellation releases seats but keeps receipts until a manual refund is confirmed."""
        order = create_cash_sale(self.cashier, self.session.pk, [self.seat.pk], "cash")
        cancel_session(self.session.pk)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payment.status, Payment.Status.REFUND_PENDING)
        today = timezone.localdate()
        self.assertEqual(build_report(today, today)["net_revenue"], "300.00")
        confirm_refund(order.pk)
        self.assertEqual(build_report(today, today)["net_revenue"], "0.00")

    def test_cancelled_unpaid_order_releases_seat_and_retains_history(self) -> None:
        """Customer cancellation preserves history while freeing its allocations."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        cancel_order(order.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        create_booking(self.other, self.session.pk, [self.seat.pk])

    def test_qr_is_signed_and_single_use(self) -> None:
        """Tampering is rejected and an admission cannot be consumed twice."""
        order = create_cash_sale(self.cashier, self.session.pk, [self.seat.pk], "cash")
        ticket = order.tickets.first()
        payload = get_qr_payload(ticket)
        with self.assertRaises(ValidationError):
            check_in_ticket(payload + "broken")
        with patch(
            "bookings.services.timezone.now",
            return_value=self.session.start_datetime - timedelta(minutes=5),
        ):
            self.assertTrue(check_in_ticket(payload).is_checked_in)
            with self.assertRaises(Conflict):
                check_in_ticket(payload)

    def test_unpaid_qr_cannot_be_used(self) -> None:
        """Knowing a token never grants admission without a confirmed payment."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        with self.assertRaises(Conflict):
            check_in_ticket(get_qr_payload(order.tickets.first()))


@override_settings(
    STORAGES=TEST_STORAGES, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class ConcurrentBookingTests(TransactionTestCase):
    """Exercise competing writes against a real file-backed SQLite database."""

    def test_two_simultaneous_requests_get_one_allocation(self) -> None:
        """Exactly one connection wins when two connections request the same seat."""
        _, hall, session = create_catalog()
        user = create_user()
        seat_id = hall.seats.first().pk
        barrier = Barrier(2)

        def reserve() -> str:
            """Start independent DB connections together and return the reservation outcome."""
            close_old_connections()
            barrier.wait(timeout=10)
            try:
                create_booking(user, session.pk, [seat_id])
                return "created"
            except Conflict:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: reserve(), range(2)))
        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(Ticket.objects.filter(is_active=True).count(), 1)
