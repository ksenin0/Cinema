"""Versioned API and Django administrative console routes."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework_simplejwt.views import TokenBlacklistView

from accounts.views import (
    CsrfView,
    LoginTokenView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileView,
    RefreshTokenView,
    RegisterView,
    WebLoginView,
    WebLogoutView,
)
from bookings.views import CashSaleView, CheckInView, OrderViewSet, TicketViewSet
from catalog.views import GenreViewSet, HallViewSet, MovieViewSet, SeatViewSet, SessionViewSet
from common.routers import PublicRootRouter
from reports.views import ReportView

router = PublicRootRouter()
router.register("genres", GenreViewSet)
router.register("movies", MovieViewSet, basename="movie")
router.register("halls", HallViewSet, basename="hall")
router.register("seats", SeatViewSet)
router.register("sessions", SessionViewSet, basename="session")
router.register("orders", OrderViewSet, basename="order")
router.register("tickets", TicketViewSet, basename="ticket")

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="api-root", permanent=False)),
    path("api/", RedirectView.as_view(pattern_name="api-root", permanent=False)),
    path("admin/", admin.site.urls),
    path("cashier/", include("cashier.urls")),
    path("staff/", include("staff.urls")),
    path("api-auth/", include("rest_framework.urls")),
    path("api/v1/", include(router.urls)),
    path("api/v1/auth/register/", RegisterView.as_view()),
    path("api/v1/auth/token/", LoginTokenView.as_view()),
    path("api/v1/auth/token/refresh/", RefreshTokenView.as_view()),
    path("api/v1/auth/token/logout/", TokenBlacklistView.as_view()),
    path("api/v1/auth/csrf/", CsrfView.as_view()),
    path("api/v1/auth/web/login/", WebLoginView.as_view()),
    path("api/v1/auth/web/logout/", WebLogoutView.as_view()),
    path("api/v1/auth/me/", ProfileView.as_view()),
    path("api/v1/auth/password/change/", PasswordChangeView.as_view()),
    path("api/v1/auth/password/reset/", PasswordResetRequestView.as_view()),
    path("api/v1/auth/password/reset/confirm/", PasswordResetConfirmView.as_view()),
    path("api/v1/cashier/sales/", CashSaleView.as_view()),
    path("api/v1/cashier/check-in/", CheckInView.as_view()),
    path("api/v1/reports/sales/", ReportView.as_view()),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "Кинотеатр — управление"
admin.site.site_title = "Кинотеатр"
admin.site.index_title = "Администрирование"

handler500 = "common.http_errors.server_error"
handler404 = "common.http_errors.page_not_found"
