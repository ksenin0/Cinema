"""Management authorization, forms and domain transitions through real HTML requests."""

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from bookings.models import Order, Payment
from bookings.services import create_cash_sale
from catalog.models import Genre, Hall, Session
from tests.factories import TEST_STORAGES, create_catalog, create_user, poster_file


@override_settings(
    STORAGES=TEST_STORAGES, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class StaffWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.movie, cls.hall, cls.session = create_catalog()
        cls.admin = create_user("manager", "admin")
        cls.cashier = create_user("seller", "cashier")
        cls.customer = create_user("viewer")
        cls.superuser = User.objects.create_superuser(
            "owner", "owner@example.test", "StrongCinema482"
        )

    def test_role_landing_pages(self):
        for user, target in [
            (self.admin, "/staff/administrator/"),
            (self.cashier, "/cashier/"),
            (self.superuser, "/staff/system/"),
        ]:
            self.client.force_login(user)
            self.assertRedirects(self.client.get("/staff/"), target)

    def test_guest_customer_and_cashier_cannot_manage(self):
        paths = [
            "/staff/administrator/",
            "/staff/system/",
            "/staff/users/",
            "/staff/users/new/",
            "/staff/catalog/movies/",
            "/staff/catalog/halls/new/",
            "/staff/orders/",
            "/staff/reports/",
        ]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 302)
        for user in [self.customer, self.cashier]:
            self.client.force_login(user)
            for path in paths:
                self.assertEqual(self.client.get(path).status_code, 403)
                self.assertEqual(self.client.post(path, {}).status_code, 403)

    def test_admin_cannot_access_or_modify_accounts(self):
        self.client.force_login(self.admin)
        for path in [
            "/staff/system/",
            "/staff/users/",
            "/staff/users/new/",
            f"/staff/users/{self.admin.pk}/",
        ]:
            self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post(path, {"is_superuser": "on"}).status_code, 403)
        self.assertNotContains(self.client.get("/staff/administrator/"), "Учётные записи")

    def test_all_management_screens_render(self):
        self.client.force_login(self.superuser)
        paths = [
            "/staff/administrator/",
            "/staff/system/",
            "/staff/users/",
            "/staff/users/new/",
            f"/staff/users/{self.admin.pk}/",
            "/staff/orders/",
            "/staff/reports/",
        ]
        for kind, obj in [
            ("movies", self.movie),
            ("genres", self.movie.genre),
            ("halls", self.hall),
            ("sessions", self.session),
            ("seats", self.hall.seats.first()),
        ]:
            paths += [f"/staff/catalog/{kind}/", f"/staff/catalog/{kind}/{obj.pk}/"]
            if kind != "seats":
                paths += [f"/staff/catalog/{kind}/new/", f"/staff/catalog/{kind}/{obj.pk}/remove/"]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])

    def test_catalog_creation_and_model_guards(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post("/staff/catalog/genres/new/", {"name": "Комедия"}).status_code, 302
        )
        self.assertTrue(Genre.objects.filter(name="Комедия").exists())
        response = self.client.post(
            "/staff/catalog/halls/new/",
            {
                "name": "Новый зал",
                "rows_count": 2,
                "seats_per_row": 3,
                "cleaning_minutes": 20,
                "vip_multiplier": "1.50",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Hall.objects.get(name="Новый зал").seats.count(), 6)
        response = self.client.post(
            "/staff/catalog/sessions/new/",
            {
                "movie": self.movie.pk,
                "hall": self.hall.pk,
                "start_datetime": timezone.localtime(self.session.start_datetime).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "base_price": "350.00",
            },
        )
        self.assertContains(response, "Накладка")
        self.assertEqual(Session.objects.count(), 1)
        response = self.client.post(
            "/staff/catalog/movies/new/",
            {
                "title": "Новая картина",
                "description": "Описание",
                "duration_minutes": 90,
                "genre": self.movie.genre_id,
                "age_limit": 6,
                "is_active": "on",
                "poster_image": poster_file(),
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_seat_rules_and_session_cancellation(self):
        self.client.force_login(self.admin)
        seat = self.hall.seats.first()
        order = create_cash_sale(self.cashier, self.session.pk, [seat.pk], "cash")
        response = self.client.post(f"/staff/catalog/seats/{seat.pk}/", {"seat_type": "vip"})
        self.assertContains(response, "Нельзя закрыть место")
        self.assertEqual(
            self.client.get(f"/staff/catalog/sessions/{self.session.pk}/remove/").status_code, 200
        )
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_cancelled)
        self.client.post(f"/staff/catalog/sessions/{self.session.pk}/remove/")
        self.session.refresh_from_db()
        order.refresh_from_db()
        self.assertTrue(self.session.is_cancelled)
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payment.status, Payment.Status.REFUND_PENDING)

    def test_order_cancellation_and_refund(self):
        self.client.force_login(self.admin)
        order = create_cash_sale(
            self.cashier, self.session.pk, [self.hall.seats.first().pk], "cash"
        )
        self.assertContains(self.client.get("/staff/orders/"), str(order.pk))
        self.assertEqual(self.client.get(f"/staff/orders/{order.pk}/action/").status_code, 405)
        self.client.post(f"/staff/orders/{order.pk}/action/", {"action": "cancel"})
        self.assertContains(self.client.get("/staff/orders/"), "Подтвердить возврат")
        self.client.post(f"/staff/orders/{order.pk}/action/", {"action": "refund"})
        order.refresh_from_db()
        self.assertEqual(order.payment.status, Payment.Status.REFUNDED)

    def account_data(self, **extra):
        return {
            "username": "newstaff",
            "email": "newstaff@example.test",
            "role": "cashier",
            "is_active": "on",
            "new_password": "StrongCinema482",
            "confirm_password": "StrongCinema482",
            **extra,
        }

    def test_superuser_creates_staff_and_ignores_privilege_injection(self):
        self.client.force_login(self.superuser)
        response = self.client.post("/staff/users/new/", self.account_data(is_superuser="on"))
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newstaff")
        self.assertTrue(user.check_password("StrongCinema482"))
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(name="Кассиры").exists())

    def test_bad_password_and_duplicate_identity_are_form_errors(self):
        self.client.force_login(self.superuser)
        self.assertContains(
            self.client.post(
                "/staff/users/new/", self.account_data(new_password="123", confirm_password="123")
            ),
            "errorlist",
        )
        self.assertFalse(User.objects.filter(username="newstaff").exists())
        self.assertContains(
            self.client.post(
                "/staff/users/new/", self.account_data(username=self.admin.username.upper())
            ),
            "errorlist",
        )

    def test_self_edit_preserves_access_and_session(self):
        self.client.force_login(self.superuser)
        data = self.account_data(
            username="owner",
            email="owner@example.test",
            new_password="NewStrongCinema483",
            confirm_password="NewStrongCinema483",
        )
        data.pop("is_active")
        self.client.post(f"/staff/users/{self.superuser.pk}/", data)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)
        self.assertTrue(self.superuser.is_superuser)
        self.assertTrue(self.superuser.check_password("NewStrongCinema483"))
        self.assertEqual(self.client.get("/staff/system/").status_code, 200)

    def test_report_period_validation_and_download_links(self):
        self.client.force_login(self.admin)
        response = self.client.get("/staff/reports/")
        self.assertContains(response, "export=xlsx")
        response = self.client.get("/staff/reports/", {"start": "2026-11-10", "end": "2026-11-01"})
        self.assertContains(response, "Выберите период")
        self.assertNotContains(response, "export=xlsx")

    def test_csrf_required_for_management_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        self.assertEqual(client.post("/staff/users/new/", self.account_data()).status_code, 403)
        self.assertEqual(client.post("/staff/catalog/genres/new/", {"name": "X"}).status_code, 403)

    def test_login_routes_admin_to_management_and_blocks_open_redirect(self):
        response = self.client.post(
            "/staff/login/",
            {"username": "manager", "password": "StrongCinema482", "next": "https://evil.example/"},
        )
        self.assertRedirects(response, "/staff/", fetch_redirect_response=False)
        self.client.logout()
        response = self.client.post(
            "/cashier/login/", {"username": "manager", "password": "StrongCinema482"}
        )
        self.assertRedirects(response, "/staff/", fetch_redirect_response=False)
