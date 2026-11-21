"""Management screens delegating state changes to existing domain operations."""

from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from rest_framework.exceptions import APIException

from accounts.models import User
from bookings.models import Order, Payment
from bookings.services import cancel_order, cancel_session, confirm_refund
from cashier.forms import CashierAuthenticationForm
from catalog.models import Hall, Movie, Session
from common.permissions import has_role
from reports.services import build_report
from staff.forms import CATALOG, AccountForm, PeriodForm


def management_required(view=None, *, system=False):
    """Authorize every HTML operation independently of visible navigation."""

    def decorate(fn):
        @wraps(fn)
        @login_required(login_url="staff:login")
        def protected(request, *args, **kwargs):
            if not has_role(request.user, "admin") or (system and not request.user.is_superuser):
                raise PermissionDenied("Этот раздел недоступен вашей роли.")
            return fn(request, *args, **kwargs)

        return never_cache(protected)

    return decorate(view) if view else decorate


class StaffLoginView(LoginView):
    template_name = "staff/login.html"
    authentication_form = CashierAuthenticationForm

    def get_default_redirect_url(self):
        return reverse("staff:home")


@login_required(login_url="staff:login")
@never_cache
@require_GET
def home(request):
    if request.user.is_superuser:
        return redirect("staff:system")
    if has_role(request.user, "admin"):
        return redirect("staff:dashboard")
    if has_role(request.user, "cashier"):
        return redirect("cashier:index")
    raise PermissionDenied("Вход доступен сотрудникам кинотеатра.")


@management_required
@require_GET
def dashboard(request):
    return render(
        request,
        "staff/dashboard.html",
        {
            "title": "Рабочий стол администратора",
            "section": "dashboard",
            "movie_count": Movie.objects.filter(is_active=True).count(),
            "hall_count": Hall.objects.filter(is_active=True).count(),
            "session_count": Session.objects.filter(
                start_datetime__gt=timezone.now(), is_cancelled=False
            ).count(),
            "refund_count": Payment.objects.filter(status=Payment.Status.REFUND_PENDING).count(),
        },
    )


@management_required(system=True)
@require_GET
def system(request):
    return render(
        request,
        "staff/system.html",
        {
            "title": "Системное управление",
            "section": "system",
            "user_count": User.objects.count(),
            "staff_count": User.objects.filter(role__in=["admin", "cashier"]).count(),
            "inactive_count": User.objects.filter(is_active=False).count(),
        },
    )


def catalog_config(kind):
    if kind not in CATALOG:
        raise Http404
    return CATALOG[kind]


@management_required
@require_GET
def catalog_list(request, kind):
    model, title, _ = catalog_config(kind)
    items = model.objects.all().order_by("pk")
    query = request.GET.get("q", "").strip()
    field = {
        "movies": "title",
        "genres": "name",
        "halls": "name",
        "sessions": "movie__title",
        "seats": "hall__name",
    }[kind]
    if query:
        items = items.filter(**{field + "__icontains": query})
    if kind == "movies":
        items = items.select_related("genre")
    if kind == "sessions":
        items = items.select_related("movie", "hall").order_by("-start_datetime")
    if kind == "seats":
        items = items.select_related("hall").order_by("hall_id", "row_number", "seat_number")
    return render(
        request,
        "staff/catalog.html",
        {
            "title": title,
            "section": kind,
            "kind": kind,
            "q": query,
            "page": Paginator(items, 25).get_page(request.GET.get("page")),
        },
    )


def form_error(form, exc):
    if isinstance(exc, ValidationError):
        for msg in exc.messages:
            form.add_error(None, msg)
    else:
        form.add_error(
            None, "Не удалось сохранить: запись связана с другими данными или уже существует."
        )


@management_required
@require_http_methods(["GET", "POST"])
def catalog_edit(request, kind, pk=None):
    model, title, form_class = catalog_config(kind)
    if kind == "seats" and pk is None:
        raise Http404
    obj = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(
        request.POST if request.method == "POST" else None, request.FILES or None, instance=obj
    )
    if kind == "halls" and obj:
        for name in ["rows_count", "seats_per_row"]:
            form.fields[name].disabled = True
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()
        except (ValidationError, IntegrityError) as exc:
            form_error(form, exc)
        else:
            messages.success(request, "Изменения сохранены.")
            return redirect("staff:catalog", kind=kind)
    return render(
        request,
        "staff/form.html",
        {
            "title": ("Изменить · " if obj else "Добавить · ") + title,
            "section": kind,
            "form": form,
            "subtitle": str(obj) if obj else "",
            "back_url": reverse("staff:catalog", kwargs={"kind": kind}),
        },
    )


@management_required
@require_http_methods(["GET", "POST"])
def catalog_remove(request, kind, pk):
    model, title, _ = catalog_config(kind)
    if kind == "seats":
        raise Http404
    obj = get_object_or_404(model, pk=pk)
    if request.method == "POST":
        try:
            with transaction.atomic():
                if kind == "sessions":
                    cancel_session(obj.pk)
                else:
                    obj.delete()
        except (ValidationError, ProtectedError, APIException) as exc:
            messages.error(
                request,
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Нельзя выполнить действие: запись используется или операция недоступна.",
            )
        else:
            messages.success(
                request,
                "Сеанс отменён."
                if kind == "sessions"
                else "Запись удалена или перенесена в архив.",
            )
        return redirect("staff:catalog", kind=kind)
    return render(
        request,
        "staff/confirm.html",
        {
            "title": "Отменить сеанс" if kind == "sessions" else "Удалить или архивировать запись",
            "section": kind,
            "object": obj,
            "explanation": (
                "Действие проверит связанные записи. При отмене сеанса билеты станут "
                "недействительными, оплаченные заказы потребуют возврата."
            ),
            "back_url": reverse("staff:catalog", kwargs={"kind": kind}),
        },
    )


@management_required
@require_GET
def orders(request):
    items = Order.objects.select_related("user", "payment").order_by("-created_at")
    status = request.GET.get("status", "")
    if status in Order.Status.values:
        items = items.filter(status=status)
    return render(
        request,
        "staff/orders.html",
        {
            "title": "Заказы и возвраты",
            "section": "orders",
            "statuses": Order.Status.choices,
            "selected_status": status,
            "page": Paginator(items, 25).get_page(request.GET.get("page")),
        },
    )


@management_required
@require_POST
def order_action(request, pk):
    get_object_or_404(Order, pk=pk)
    action = request.POST.get("action")
    if action not in {"cancel", "refund"}:
        raise Http404
    try:
        if action == "cancel":
            cancel_order(pk, allow_paid=True)
        else:
            confirm_refund(pk)
    except APIException as exc:
        messages.error(request, str(exc.detail))
    else:
        messages.success(
            request, "Заказ отменён." if action == "cancel" else "Учебный возврат подтверждён."
        )
    return redirect("staff:orders")


@management_required
@require_GET
def report(request):
    today = timezone.localdate()
    form = PeriodForm(request.GET or {"start": today.replace(day=1), "end": today})
    result = build_report(**form.cleaned_data) if form.is_valid() else None
    params = urlencode({k: v.isoformat() for k, v in form.cleaned_data.items()}) if result else ""
    return render(
        request,
        "staff/report.html",
        {
            "title": "Отчёты",
            "section": "report",
            "form": form,
            "report": result,
            "export_query": params,
        },
    )


@management_required(system=True)
@require_GET
def users(request):
    q = request.GET.get("q", "").strip()
    items = User.objects.filter(Q(username__icontains=q) | Q(email__icontains=q)).order_by(
        "username"
    )
    return render(
        request,
        "staff/users.html",
        {
            "title": "Учётные записи",
            "section": "users",
            "q": q,
            "page": Paginator(items, 25).get_page(request.GET.get("page")),
        },
    )


@management_required(system=True)
@require_http_methods(["GET", "POST"])
def user_edit(request, pk=None):
    obj = get_object_or_404(User, pk=pk) if pk else None
    form = AccountForm(
        request.POST if request.method == "POST" else None, instance=obj, actor=request.user
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                saved = form.save()
                if saved.pk == request.user.pk:
                    update_session_auth_hash(request, saved)
        except (ValidationError, IntegrityError) as exc:
            form_error(form, exc)
        else:
            messages.success(request, "Учётная запись сохранена.")
            return redirect("staff:users")
    return render(
        request,
        "staff/form.html",
        {
            "title": "Изменить пользователя" if obj else "Создать пользователя",
            "section": "users",
            "form": form,
            "back_url": reverse("staff:users"),
            "subtitle": (
                "Суперпользователи и расширенные разрешения настраиваются "
                "в технической панели Django."
            ),
        },
    )
