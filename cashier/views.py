"""Protected HTML pages and read models for the cashier workspace."""

from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from bookings.models import Order
from bookings.serializers import OrderSerializer
from cashier.forms import CashierAuthenticationForm
from catalog.models import Session
from common.permissions import has_role


def personnel_required(view):
    """Share active-role authorization across HTML and workspace read endpoints."""

    @wraps(view)
    @login_required(login_url="cashier:login")
    def protected(request, *args, **kwargs):
        if not has_role(request.user, "cashier", "admin"):
            raise PermissionDenied("Касса доступна только сотрудникам кинотеатра.")
        return view(request, *args, **kwargs)

    return never_cache(protected)


class CashierLoginView(LoginView):
    """Normal HTML login with Django CSRF and safe next-URL validation."""

    template_name = "cashier/login.html"
    authentication_form = CashierAuthenticationForm
    next_page = reverse_lazy("cashier:index")

    def get_default_redirect_url(self):
        if self.request.user.is_superuser or self.request.user.role == "admin":
            return reverse_lazy("staff:home")
        return super().get_default_redirect_url()


class CashierLogoutView(LogoutView):
    """POST-only logout prevents cross-site GET logout."""

    next_page = reverse_lazy("cashier:login")


@personnel_required
@require_GET
def index(request):
    """Render the workspace; every mutation goes through the existing REST services."""
    return render(request, "cashier/index.html", {"time_zone": settings.TIME_ZONE})


@personnel_required
@require_GET
def schedule(request):
    """Return upcoming sellable sessions, with server time for browser cutoffs."""
    now = timezone.now()
    sessions = (
        Session.objects.filter(
            is_cancelled=False,
            start_datetime__gt=now,
            movie__is_active=True,
            hall__is_active=True,
        )
        .select_related("movie", "hall")
        .order_by("start_datetime", "id")
    )
    return JsonResponse(
        {
            "server_time": now.isoformat(),
            "sessions": [
                {
                    "id": s.pk,
                    "movie_title": s.movie.title,
                    "age_limit": s.movie.age_limit,
                    "hall_name": s.hall.name,
                    "start_datetime": s.start_datetime.isoformat(),
                    "base_price": str(s.base_price),
                }
                for s in sessions
            ],
        }
    )


def sale_orders():
    """Load ticket read models without an N+1 query for each seat and screening."""
    return Order.objects.select_related("payment").prefetch_related(
        "tickets__seat", "tickets__session__movie", "tickets__session__hall"
    )


@personnel_required
@require_GET
def recent_sales(request):
    """Let cashiers recover issued tickets after closing the receipt or losing a response."""
    orders = (
        sale_orders()
        .filter(created_by=request.user, user__isnull=True, status=Order.Status.PAID)
        .order_by("-created_at")[:20]
    )
    return JsonResponse({"orders": OrderSerializer(orders, many=True).data})


@personnel_required
@require_GET
def receipt(request, order_id):
    """Printable issued tickets; personnel have the same read rights as in the API."""
    order = get_object_or_404(sale_orders(), pk=order_id, status=Order.Status.PAID)
    return render(request, "cashier/receipt.html", {"order": order})
