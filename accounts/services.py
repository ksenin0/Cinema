"""Account lifecycle use cases independent from HTTP controllers."""

import uuid

from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from bookings.models import Order, Payment
from bookings.services import cancel_order
from notifications.services import enqueue_email


@transaction.atomic
def register_client(data: dict) -> User:
    """Create a client with a Django-hashed password and enqueue a welcome message."""
    user = User.objects.create_user(**data, role=User.Role.CLIENT)
    enqueue_email(user, "Добро пожаловать", "Регистрация в системе «Кинотеатр» успешно завершена.")
    return user


def request_password_reset(email: str) -> None:
    """Queue a one-time reset code for known users without revealing account existence."""
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        enqueue_email(
            user,
            "Сброс пароля",
            f"Код пользователя: {uid}\nОдноразовый токен: {token}\n"
            "Если вы не запрашивали сброс, проигнорируйте письмо.",
        )


@transaction.atomic
def deactivate_user(user: User) -> None:
    """Anonymize identity, cancel unpaid holds, and preserve financial/ticket history."""
    for order in user.orders.filter(status=Order.Status.PENDING):
        cancel_order(order.pk)
    Order.objects.filter(user=user).update(user=None)
    Order.objects.filter(created_by=user).update(created_by=None)
    Payment.objects.filter(recorded_by=user).update(recorded_by=None)
    user.notification_set.all().delete()
    suffix = uuid.uuid4().hex
    user.username = f"deleted_{suffix}"
    user.email = f"deleted_{suffix}@invalid.local"
    user.first_name = user.last_name = user.phone = ""
    user.is_active = False
    user.set_unusable_password()
    user.save()
