"""Translate domain and framework errors to the API error contract."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler


class Conflict(APIException):
    """The resource changed or is already reserved; HTTP 409."""

    status_code = 409
    default_detail = "Данные изменились. Обновите страницу и повторите запрос."
    default_code = "conflict"


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """Convert known exceptions into a standard error response; hide SQL details."""
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    if isinstance(exc, ProtectedError):
        exc = Conflict("Удаление запрещено: существуют связанные данные.")
    elif isinstance(exc, IntegrityError):
        exc = Conflict("Нарушено ограничение целостности или уникальности данных.")
    response = exception_handler(exc, context)
    if response is not None:
        errors = response.data
        message = (
            errors.get("detail", "Проверьте данные запроса.")
            if isinstance(errors, dict)
            else "Проверьте данные запроса."
        )
        response.data = {"status": "error", "message": str(message), "errors": errors}
    return response
