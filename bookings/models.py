"""Shared booking, ticket, and payment persistence models."""

import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Order(models.Model):
    """An immutable price snapshot for a group of reserved or purchased seats."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает оплаты"
        PAID = "paid", "Оплачен"
        CANCELLED = "cancelled", "Отменён"
        EXPIRED = "expired", "Бронь истекла"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_sales",
    )
    total_price = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(0)]
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "expires_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_price__gte=0), name="order_nonnegative_total"
            )
        ]


class Ticket(models.Model):
    """Historical ticket with a conditional unique constraint for live seat allocations."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="tickets")
    session = models.ForeignKey("catalog.Session", on_delete=models.PROTECT, related_name="tickets")
    seat = models.ForeignKey("catalog.Seat", on_delete=models.PROTECT, related_name="tickets")
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    qr_code_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_checked_in = models.BooleanField(default=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["seat__row_number", "seat__seat_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "seat"],
                condition=models.Q(is_active=True),
                name="unique_active_session_seat",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0), name="ticket_nonnegative_price"
            ),
        ]


class Payment(models.Model):
    """Accounting record; online payment integration has a separate gateway boundary."""

    class Method(models.TextChoices):
        CASH = "cash", "Наличные"
        CARD = "card", "Банковский терминал"
        ONLINE = "online", "Онлайн"

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Оплачен"
        REFUND_PENDING = "refund_pending", "Требует возврата"
        REFUNDED = "refunded", "Возвращён"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="payment")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    method = models.CharField(max_length=10, choices=Method.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCEEDED)
    external_reference = models.CharField(max_length=200, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="payment_nonnegative_amount"
            )
        ]
