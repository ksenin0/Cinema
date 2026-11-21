"""JSON errors for API failures raised outside DRF request dispatch."""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views import defaults
from django.views.csrf import csrf_failure as django_csrf_failure


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """Return a standard API error for a CSRF failure, keeping Django's HTML elsewhere."""
    if request.path.startswith("/api/"):
        return JsonResponse(
            {
                "status": "error",
                "message": "Проверка CSRF не пройдена.",
                "errors": {"csrf": "Получите новый CSRF-токен и повторите запрос."},
            },
            status=403,
        )
    return django_csrf_failure(request, reason=reason)


def server_error(request: HttpRequest) -> HttpResponse:
    """Hide internal server details behind a stable JSON error in production."""
    if request.path.startswith("/api/"):
        return JsonResponse(
            {"status": "error", "message": "Внутренняя ошибка сервера.", "errors": {}}, status=500
        )
    return defaults.server_error(request)


def page_not_found(request: HttpRequest, exception: Exception) -> HttpResponse:
    """Provide the same JSON envelope for unresolved API routes."""
    if request.path.startswith("/api/"):
        return JsonResponse(
            {"status": "error", "message": "Ресурс не найден.", "errors": {}}, status=404
        )
    return defaults.page_not_found(request, exception)
