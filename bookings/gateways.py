"""Replaceable payment adapter with a local coursework implementation."""

from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework.exceptions import APIException

from bookings.models import Order
from bookings.services import record_demo_online_payment


class GatewayUnavailable(APIException):
    """Report an unconfigured payment integration as HTTP 503."""

    status_code = 503
    default_detail = "Онлайн-эквайринг ещё не подключён. Оплатите заказ в кассе."


class PaymentGateway(Protocol):
    """Interface for provider-specific payment initiation adapters."""

    def initiate(self, order: Order) -> Order:
        """Return the paid order or raise an error without a partial state transition."""
        ...


class UnconfiguredGateway:
    """Fail explicitly until a real acquiring provider and webhook are implemented."""

    def initiate(self, order: Order) -> Order:
        """Raise GatewayUnavailable without changing order or payment state."""
        raise GatewayUnavailable()


class DemoPaymentGateway:
    """Simulate clicking Pay without requesting card data or making network calls."""

    def initiate(self, order: Order) -> Order:
        """Return the atomically paid order, with idempotent retry handling."""
        return record_demo_online_payment(order.pk, order.user)


def get_payment_gateway() -> PaymentGateway:
    """Resolve the configured gateway adapter without coupling controllers to a provider."""
    return import_string(settings.PAYMENT_GATEWAY_CLASS)()
