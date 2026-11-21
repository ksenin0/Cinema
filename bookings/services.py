"""Atomic booking use cases. Views and administration delegate state transitions here."""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import User
from bookings.models import Order, Payment, Ticket
from bookings.pricing import PricePolicy, StandardPricePolicy
from catalog.models import Seat, Session
from common.exceptions import Conflict
from notifications.services import enqueue_email


@transaction.atomic
def expire_orders() -> int:
    """Expire unpaid holds whose deadline has passed and release their seat allocations."""
    orders = Order.objects.filter(status=Order.Status.PENDING, expires_at__lte=timezone.now())
    Ticket.objects.filter(order__in=orders, is_active=True).update(is_active=False)
    return orders.update(status=Order.Status.EXPIRED)


def validate_selection(session: Session, seat_ids: list[int]) -> list[Seat]:
    """Return selected available hall seats; reject past sessions and invalid selections."""
    if session.is_cancelled or not session.hall.is_active or not session.movie.is_active:
        raise ValidationError("Сеанс недоступен для продажи.")
    if session.start_datetime <= timezone.now():
        raise ValidationError("Продажа билетов на начавшийся сеанс закрыта.")
    if not seat_ids or len(seat_ids) > 20 or len(set(seat_ids)) != len(seat_ids):
        raise ValidationError({"seat_ids": "Выберите от 1 до 20 различных мест."})
    seats = list(Seat.objects.filter(pk__in=seat_ids, hall=session.hall, is_available=True))
    if len(seats) != len(seat_ids):
        raise ValidationError({"seat_ids": "Есть недоступные места или места из другого зала."})
    if Ticket.objects.filter(session=session, seat_id__in=seat_ids, is_active=True).exists():
        raise Conflict("Одно или несколько мест уже заняты.")
    return seats


@transaction.atomic
def create_booking(
    user: User | None,
    session_id: int,
    seat_ids: list[int],
    created_by: User | None = None,
    price_policy: PricePolicy | None = None,
) -> Order:
    """Create a ten-minute hold at server-calculated prices; raise ValidationError/Conflict."""
    expire_orders()
    session = get_object_or_404(Session.objects.select_related("movie", "hall"), pk=session_id)
    seats = validate_selection(session, seat_ids)
    policy = price_policy or StandardPricePolicy()
    prices = [(seat, policy.calculate(session, seat)) for seat in seats]
    order = Order.objects.create(
        user=user,
        created_by=created_by,
        total_price=sum((price for _, price in prices), Decimal("0.00")),
        expires_at=timezone.now() + timedelta(minutes=settings.RESERVATION_TIMEOUT_MINUTES),
    )
    Ticket.objects.bulk_create(
        [Ticket(order=order, session=session, seat=seat, price=price) for seat, price in prices]
    )
    return order


def record_payment(order_id: object, method: str, actor: User, reference: str = "") -> Order:
    """Simulate a cashier payment without requesting any bank or card details."""
    if method not in {Payment.Method.CASH, Payment.Method.CARD}:
        raise ValidationError("Выберите демонстрационную оплату наличными или картой.")
    return _complete_payment(order_id, method, actor, reference)


def record_demo_online_payment(order_id: object, actor: User | None) -> Order:
    """Simulate a successful online payment once; no external gateway is contacted."""
    return _complete_payment(order_id, Payment.Method.ONLINE, actor, f"demo-online-{order_id}")


@transaction.atomic
def _complete_payment(order_id: object, method: str, actor: User | None, reference: str) -> Order:
    """Apply shared payment invariants, create a receipt, and issue paid tickets atomically."""
    order = get_object_or_404(Order.objects.select_related("user"), pk=order_id)
    if order.status == Order.Status.PAID:
        if order.payment.method != method or order.payment.external_reference != reference:
            raise Conflict("Заказ уже оплачен другим способом или с другим реквизитом.")
        return order
    if order.status != Order.Status.PENDING or order.expires_at <= timezone.now():
        raise Conflict("Бронь истекла или заказ отменён.")
    if order.tickets.filter(session__start_datetime__lte=timezone.now()).exists():
        raise Conflict("Сеанс уже начался.")
    if (
        order.tickets.filter(is_active=False).exists()
        or order.tickets.filter(session__is_cancelled=True).exists()
    ):
        raise Conflict("Билеты недействительны или сеанс отменён.")
    Payment.objects.create(
        order=order,
        amount=order.total_price,
        method=method,
        recorded_by=actor,
        external_reference=reference,
    )
    order.status = Order.Status.PAID
    order.save(update_fields=["status"])
    enqueue_email(
        order.user,
        "Билеты оплачены",
        f"Заказ {order.pk}. Оплачено: {order.total_price} руб.",
        order,
    )
    return order


@transaction.atomic
def create_cash_sale(
    actor: User, session_id: int, seat_ids: list[int], method: str, reference: str = ""
) -> Order:
    """Reserve and pay for a walk-in sale in one atomic transaction."""
    order = create_booking(None, session_id, seat_ids, created_by=actor)
    return record_payment(order.pk, method, actor, reference)


@transaction.atomic
def cancel_order(order_id: object, allow_paid: bool = False) -> Order:
    """Cancel a pending order; personnel can additionally flag a paid order for refund."""
    order = get_object_or_404(Order, pk=order_id)
    if order.status in {Order.Status.CANCELLED, Order.Status.EXPIRED}:
        return order
    if order.status == Order.Status.PAID:
        if not allow_paid:
            raise Conflict("Возврат оплаченного заказа оформляет сотрудник кинотеатра.")
        if order.tickets.filter(is_checked_in=True).exists():
            raise Conflict("Нельзя вернуть заказ с использованным билетом.")
        Payment.objects.filter(order=order).update(status=Payment.Status.REFUND_PENDING)
    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status"])
    order.tickets.update(is_active=False)
    return order


@transaction.atomic
def confirm_refund(order_id: object) -> Payment:
    """Record a completed manual refund; reject orders without a requested refund."""
    payment = get_object_or_404(Payment, order_id=order_id)
    if payment.status == Payment.Status.REFUNDED:
        return payment
    if payment.status != Payment.Status.REFUND_PENDING:
        raise Conflict("Для заказа не запрошен возврат.")
    payment.status = Payment.Status.REFUNDED
    payment.refunded_at = timezone.now()
    payment.save(update_fields=["status", "refunded_at"])
    return payment


@transaction.atomic
def cancel_session(session_id: int) -> Session:
    """Cancel a screening, release its holds, flag paid orders for refund, and notify clients."""
    session = get_object_or_404(Session, pk=session_id)
    if session.is_cancelled:
        return session
    session.is_cancelled = True
    session.save(update_fields=["is_cancelled"])
    orders = Order.objects.filter(tickets__session=session).distinct().select_related("user")
    for order in orders:
        # A cancelled screening invalidates admission even if a ticket was scanned earlier.
        if order.status == Order.Status.PAID:
            Payment.objects.filter(order=order).update(status=Payment.Status.REFUND_PENDING)
        if order.status in {Order.Status.PAID, Order.Status.PENDING}:
            order.status = Order.Status.CANCELLED
            order.save(update_fields=["status"])
            order.tickets.update(is_active=False)
            enqueue_email(
                order.user,
                "Сеанс отменён",
                f"Сеанс {session} отменён. Для возврата обратитесь в кассу.",
            )
    return session


def get_qr_payload(ticket: Ticket) -> str:
    """Return a signed opaque ticket identifier, with no personal data in the QR payload."""
    return signing.dumps(
        {"token": str(ticket.qr_code_token)}, salt="cinema.ticket.v1", compress=True
    )


@transaction.atomic
def check_in_ticket(payload: str) -> Ticket:
    """Validate a signed QR and consume admission once; reject unpaid/expired/used tickets."""
    try:
        token = signing.loads(payload, salt="cinema.ticket.v1")["token"]
    except (signing.BadSignature, KeyError, TypeError) as exc:
        raise ValidationError("Некорректный QR-код.") from exc
    ticket = get_object_or_404(
        Ticket.objects.select_related("order", "session"), qr_code_token=token
    )
    if (
        not ticket.is_active
        or ticket.order.status != Order.Status.PAID
        or ticket.session.is_cancelled
    ):
        raise Conflict("Билет недействителен или не оплачен.")
    if ticket.is_checked_in:
        raise Conflict("Билет уже использован.")
    now = timezone.now()
    if (
        now < ticket.session.start_datetime - timedelta(minutes=30)
        or now >= ticket.session.end_datetime
    ):
        raise Conflict("Вход доступен за 30 минут до начала и до окончания сеанса.")
    ticket.is_checked_in = True
    ticket.checked_in_at = now
    ticket.save(update_fields=["is_checked_in", "checked_in_at"])
    return ticket
