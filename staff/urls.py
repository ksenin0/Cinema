"""Named management routes, leaving Django Admin at its existing address."""

from django.urls import path

from staff import views

app_name = "staff"
urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.StaffLoginView.as_view(), name="login"),
    path("administrator/", views.dashboard, name="dashboard"),
    path("system/", views.system, name="system"),
    path("users/", views.users, name="users"),
    path("users/new/", views.user_edit, name="user-new"),
    path("users/<int:pk>/", views.user_edit, name="user-edit"),
    path("orders/", views.orders, name="orders"),
    path("orders/<uuid:pk>/action/", views.order_action, name="order-action"),
    path("reports/", views.report, name="report"),
    path("catalog/<str:kind>/", views.catalog_list, name="catalog"),
    path("catalog/<str:kind>/new/", views.catalog_edit, name="catalog-new"),
    path("catalog/<str:kind>/<int:pk>/", views.catalog_edit, name="catalog-edit"),
    path("catalog/<str:kind>/<int:pk>/remove/", views.catalog_remove, name="catalog-remove"),
]
