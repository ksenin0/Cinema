"""Human-facing staff routes, separate from the REST resource namespace."""

from django.urls import path

from cashier import views

app_name = "cashier"
urlpatterns = [
    path("", views.index, name="index"),
    path("login/", views.CashierLoginView.as_view(), name="login"),
    path("logout/", views.CashierLogoutView.as_view(), name="logout"),
    path("schedule/", views.schedule, name="schedule"),
    path("recent-sales/", views.recent_sales, name="recent-sales"),
    path("receipt/<uuid:order_id>/", views.receipt, name="receipt"),
]
