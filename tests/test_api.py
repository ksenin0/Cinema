"""Integration tests for roles, sessions/JWT, ownership and output contracts."""

from datetime import timedelta
from io import BytesIO, StringIO

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from bookings.models import Order, Payment
from bookings.services import create_booking, record_payment
from notifications.models import Notification
from tests.factories import TEST_STORAGES, create_catalog, create_user


@override_settings(
    STORAGES=TEST_STORAGES, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class ApiTests(APITestCase):
    """Verify public API behavior and prevent user-controlled privilege escalation."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Prepare shared identities and a screening for transactional integration tests."""
        cls.movie, cls.hall, cls.session = create_catalog()
        cls.user = create_user()
        cls.other = create_user("other")
        cls.cashier = create_user("cashier", "cashier")
        cls.admin = create_user("manager", "admin")
        cls.seat = cls.hall.seats.first()

    def setUp(self) -> None:
        """Clear shared throttle counters before every independent HTTP scenario."""
        cache.clear()

    def test_public_reads_and_private_mutations(self) -> None:
        """Guests may browse the catalog but cannot create movies or reserve seats."""
        self.assertEqual(self.client.get("/api/v1/movies/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/v1/sessions/{self.session.pk}/seat-map/").status_code, 200
        )
        self.assertEqual(self.client.post("/api/v1/orders/", {}).status_code, 401)
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post("/api/v1/movies/", {}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/reports/sales/").status_code, 403)

    def test_registration_hashes_password_and_cannot_assign_staff_role(self) -> None:
        """A registration payload can never create a cashier or a superuser."""
        payload = {
            "username": "new_client",
            "email": "NEW@example.com",
            "first_name": "Имя",
            "phone": "+79990000000",
            "password": "StrongClient482",
            "password_confirm": "StrongClient482",
            "role": "admin",
            "is_staff": True,
            "is_superuser": True,
        }
        response = self.client.post("/api/v1/auth/register/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(username="new_client")
        self.assertEqual(user.role, "client")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(payload["password"]))
        self.assertNotEqual(user.password, payload["password"])
        self.assertEqual(user.email, "new@example.com")
        self.assertTrue(Notification.objects.filter(user=user).exists())

    def test_case_insensitive_uniqueness_and_password_policy(self) -> None:
        """Login/email case variants and weak passwords receive structured validation errors."""
        payload = {
            "username": "CLIENT",
            "email": "CLIENT@example.com",
            "first_name": "Name",
            "phone": "123",
            "password": "weak",
            "password_confirm": "weak",
        }
        response = self.client.post("/api/v1/auth/register/", payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], "error")
        self.assertIn("username", response.data["errors"])
        payload.update(username="brandnew", email="brandnew@example.com")
        self.assertEqual(self.client.post("/api/v1/auth/register/", payload).status_code, 400)

    def test_customer_cannot_read_other_orders_or_tickets(self) -> None:
        """Ownership filtering applies to both order history and ticket downloads."""
        order = create_booking(self.other, self.session.pk, [self.seat.pk])
        ticket = order.tickets.first()
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f"/api/v1/orders/{order.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/tickets/{ticket.pk}/download/").status_code, 404)

    def test_customer_booking_ignores_client_price_and_hides_unpaid_qr(self) -> None:
        """The server calculates money and withholds QR payloads before payment."""
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/v1/orders/",
            {
                "session_id": self.session.pk,
                "seat_ids": [self.seat.pk],
                "total_price": "0.01",
                "status": "paid",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["total_price"], "300.00")
        self.assertEqual(response.data["status"], "pending")
        self.assertIsNone(response.data["tickets"][0]["qr_payload"])
        order_id = response.data["id"]
        self.assertEqual(
            self.client.post(f"/api/v1/orders/{order_id}/pay/", {"method": "cash"}).status_code, 403
        )

    def test_cashier_sale_and_idempotent_payment(self) -> None:
        """A cashier can atomically sell seats but cannot change catalog configuration."""
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.post("/api/v1/halls/", {}).status_code, 403)
        response = self.client.post(
            "/api/v1/cashier/sales/",
            {"session_id": self.session.pk, "seat_ids": [self.seat.pk], "method": "cash"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "paid")
        self.assertIsNotNone(response.data["tickets"][0]["qr_payload"])
        retry = self.client.post(f"/api/v1/orders/{response.data['id']}/pay/", {"method": "cash"})
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(Payment.objects.count(), 1)

    @override_settings(PAYMENT_GATEWAY_CLASS="bookings.gateways.UnconfiguredGateway")
    def test_online_payment_is_explicitly_unconfigured(self) -> None:
        """Unconfigured online acquiring never creates a fictitious paid order."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        self.client.force_authenticate(self.user)
        response = self.client.post(f"/api/v1/orders/{order.pk}/online-payment/")
        self.assertEqual(response.status_code, 503)
        order.refresh_from_db()
        self.assertEqual(order.status, "pending")
        self.assertFalse(Payment.objects.exists())

    def test_api_index_and_homepage_open_without_login(self) -> None:
        """Both shared entry addresses open the public index while private APIs stay private."""
        for path in ("/", "/api/", "/api/v1/", "/api/v1"):
            response = self.client.get(path, follow=True)
            self.assertEqual(response.status_code, 200, (path, response.content))
            self.assertIn("movies", response.data)
        html = self.client.get("/api/v1/", HTTP_ACCEPT="text/html")
        self.assertEqual(html.status_code, 200)
        self.assertIn("text/html", html["Content-Type"])
        self.assertEqual(self.client.get("/api/v1/orders/").status_code, 401)

    def test_demo_online_payment_needs_no_payment_details_and_is_repeatable(self) -> None:
        """One empty POST pays the order, issues QR tickets, and queues a local notification."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        self.client.force_authenticate(self.user)
        url = f"/api/v1/orders/{order.pk}/online-payment/"
        for _ in range(2):
            response = self.client.post(url, {}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["status"], "paid")
            self.assertEqual(response.data["payment"]["method"], "online")
            self.assertTrue(response.data["tickets"][0]["qr_payload"])
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        self.assertEqual(Notification.objects.filter(order=order).count(), 1)

    def test_demo_payment_rejects_other_users_expired_and_cancelled_orders(self) -> None:
        """Simulation preserves ownership and reservation deadlines."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        url = f"/api/v1/orders/{order.pk}/online-payment/"
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_authenticate(self.user)
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.post(url).status_code, 409)
        replacement = create_booking(self.user, self.session.pk, [self.seat.pk])
        self.client.post(f"/api/v1/orders/{replacement.pk}/cancel/")
        self.assertEqual(
            self.client.post(f"/api/v1/orders/{replacement.pk}/online-payment/").status_code, 409
        )
        self.assertFalse(Payment.objects.exists())

    def test_cashier_card_payment_needs_only_the_button_choice(self) -> None:
        """The card button simulates payment with no terminal or card number."""
        self.client.force_authenticate(self.cashier)
        response = self.client.post(
            "/api/v1/cashier/sales/",
            {
                "session_id": self.session.pk,
                "seat_ids": [self.seat.pk],
                "method": "card",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], "paid")
        self.assertEqual(response.data["payment"]["method"], "card")

    def test_order_list_expires_overdue_holds(self) -> None:
        """Order history reflects expired reservations even when the worker is stopped."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/v1/orders/")
        self.assertEqual(response.data["results"][0]["status"], "expired")

    def test_layout_updates_are_atomic(self) -> None:
        """A foreign hall cell rolls back all changes to the requested hall."""
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/halls/{self.hall.pk}/layout/",
            {
                "seats": [
                    {"id": self.seat.pk, "seat_type": "vip", "is_available": True},
                    {"id": 999999, "seat_type": "standard", "is_available": False},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.seat.refresh_from_db()
        self.assertEqual(self.seat.seat_type, "standard")

    def test_invalid_filters_are_validation_errors(self) -> None:
        """Bad query parameters never become uncaught ORM errors."""
        for url in (
            "/api/v1/movies/?genre=abc",
            "/api/v1/sessions/?date=2026-99-99",
            "/api/v1/sessions/?hall=abc",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["status"], "error")

    def test_movie_search_ignores_cyrillic_case_on_sqlite(self) -> None:
        """Russian names remain discoverable when a mobile user types them in lowercase."""
        response = self.client.get("/api/v1/movies/", {"search": "тЕсТоВыЙ"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.movie.pk)

    def test_jwt_refresh_rotation_and_logout(self) -> None:
        """JWT refresh tokens rotate and revoked refresh tokens cannot be reused."""
        response = self.client.post(
            "/api/v1/auth/token/", {"username": "client", "password": "StrongCinema482"}
        )
        self.assertEqual(response.status_code, 200, response.data)
        old_refresh = response.data["refresh"]
        response = self.client.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self.client.post("/api/v1/auth/token/refresh/", {"refresh": old_refresh}).status_code,
            401,
        )
        refresh = response.data["refresh"]
        self.assertEqual(
            self.client.post("/api/v1/auth/token/logout/", {"refresh": refresh}).status_code, 200
        )
        self.assertEqual(
            self.client.post("/api/v1/auth/token/refresh/", {"refresh": refresh}).status_code, 401
        )

    def test_web_login_requires_csrf_and_uses_a_django_session(self) -> None:
        """Personnel session login requires CSRF protection even before authentication."""
        browser = APIClient(enforce_csrf_checks=True)
        payload = {"username": "cashier", "password": "StrongCinema482"}
        self.assertEqual(browser.post("/api/v1/auth/web/login/", payload).status_code, 403)
        token = browser.get("/api/v1/auth/csrf/").data["csrf_token"]
        response = browser.post("/api/v1/auth/web/login/", payload, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("_auth_user_id", browser.session)
        self.assertEqual(browser.get("/api/v1/auth/me/").status_code, 200)

    def test_password_change_checks_current_password_and_revokes_access(self) -> None:
        """A changed password invalidates earlier access JWTs and needs the previous secret."""
        access = self.client.post(
            "/api/v1/auth/token/", {"username": "client", "password": "StrongCinema482"}
        ).data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        payload = {
            "current_password": "wrong",
            "new_password": "Replacement482",
            "new_password_confirm": "Replacement482",
        }
        self.assertEqual(
            self.client.post("/api/v1/auth/password/change/", payload).status_code, 400
        )
        payload["current_password"] = "StrongCinema482"
        self.assertEqual(
            self.client.post("/api/v1/auth/password/change/", payload).status_code, 200
        )
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)

    def test_reset_token_is_single_use_and_request_is_non_enumerating(self) -> None:
        """Reset requests return identical responses and tokens work exactly once."""
        known = self.client.post("/api/v1/auth/password/reset/", {"email": self.user.email})
        unknown = self.client.post("/api/v1/auth/password/reset/", {"email": "unknown@example.com"})
        self.assertEqual(known.data, unknown.data)
        message = Notification.objects.get(user=self.user)
        lines = message.body.splitlines()
        payload = {
            "uid": lines[0].split(": ", 1)[1],
            "token": lines[1].split(": ", 1)[1],
            "new_password": "Replacement482",
            "new_password_confirm": "Replacement482",
        }
        self.assertEqual(
            self.client.post("/api/v1/auth/password/reset/confirm/", payload).status_code, 200
        )
        self.assertEqual(
            self.client.post("/api/v1/auth/password/reset/confirm/", payload).status_code, 400
        )

    def test_deactivation_preserves_anonymous_financial_history(self) -> None:
        """Paid records survive deactivation while customer PII and ownership are removed."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        record_payment(order.pk, "cash", self.cashier)
        self.client.force_authenticate(self.user)
        response = self.client.delete(
            "/api/v1/auth/me/", {"current_password": "StrongCinema482"}, format="json"
        )
        self.assertEqual(response.status_code, 204, response.data)
        order.refresh_from_db()
        self.user.refresh_from_db()
        self.assertIsNone(order.user_id)
        self.assertFalse(self.user.is_active)
        self.assertNotIn("client@example.com", self.user.email)
        self.assertEqual(order.status, "paid")
        self.assertTrue(Payment.objects.filter(order=order).exists())
        self.assertFalse(Notification.objects.filter(user=self.user).exists())

    def test_report_and_ticket_exports_are_real_files(self) -> None:
        """CSV/XLSX/PDF reports and PNG/PDF tickets have valid file containers."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        record_payment(order.pk, "cash", self.cashier)
        ticket = order.tickets.first()
        self.client.force_authenticate(self.admin)
        date = timezone.localdate().isoformat()
        url = f"/api/v1/reports/sales/?start={date}&end={date}"
        self.assertEqual(self.client.get(url).status_code, 200)
        csv = self.client.get(url + "&export=csv")
        self.assertTrue(csv.content.startswith(b"\xef\xbb\xbf"))
        xlsx = self.client.get(url + "&export=xlsx")
        workbook = load_workbook(BytesIO(xlsx.content))
        self.assertEqual(workbook.active["A1"].value, "start")
        self.assertTrue(self.client.get(url + "&export=pdf").content.startswith(b"%PDF"))
        for extension, signature in (("png", b"\x89PNG"), ("pdf", b"%PDF"), ("qr", b"\x89PNG")):
            response = self.client.get(f"/api/v1/tickets/{ticket.pk}/download/?export={extension}")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(signature))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_worker_attaches_paid_ticket_and_records_delivery(self) -> None:
        """Delivery is retryable and a successfully sent message is not sent again."""
        order = create_booking(self.user, self.session.pk, [self.seat.pk])
        record_payment(order.pk, "cash", self.cashier)
        call_command("send_notifications", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 2)
        call_command("send_notifications", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

    def test_cashier_and_admin_groups_have_narrow_permissions(self) -> None:
        """A content administrator can edit catalog objects but cannot manage identities."""
        self.assertTrue(self.admin.has_perm("catalog.add_movie"))
        self.assertFalse(self.admin.has_perm("accounts.change_user"))
        self.assertTrue(self.cashier.has_perm("catalog.view_session"))
        self.assertFalse(self.cashier.has_perm("catalog.change_session"))
