"""Cashier HTML access and real session-authenticated sales workflow."""

import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bookings.models import Order, Payment
from bookings.services import create_booking, create_cash_sale
from tests.factories import TEST_STORAGES, create_catalog, create_user


@override_settings(
    STORAGES=TEST_STORAGES, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class CashierWorkspaceTests(TestCase):
    """Exercise personnel pages and the same endpoints used by their JavaScript."""

    @classmethod
    def setUpTestData(cls):
        cls.movie, cls.hall, cls.session = create_catalog()
        cls.cashier = create_user("cashier", "cashier")
        cls.other_cashier = create_user("cashier2", "cashier")
        cls.admin = create_user("manager", "admin")
        cls.customer = create_user("customer")
        cls.seat = cls.hall.seats.first()

    def setUp(self):
        cache.clear()

    def sale_payload(self, method="cash"):
        return {"session_id": self.session.pk, "seat_ids": [self.seat.pk], "method": method}

    def test_guest_redirect_and_customer_denial_on_all_workspace_reads(self):
        order = create_cash_sale(self.cashier, **self.sale_payload())
        paths = [
            "/cashier/",
            "/cashier/schedule/",
            "/cashier/recent-sales/",
            f"/cashier/receipt/{order.pk}/",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertRedirects(self.client.get(path), f"/cashier/login/?next={path}")
        self.client.force_login(self.customer)
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_cashier_and_administrator_can_open_workspace(self):
        for user in [self.cashier, self.admin]:
            self.client.force_login(user)
            response = self.client.get("/cashier/")
            self.assertContains(response, "Наличные")
            self.assertContains(response, "Карта")
            self.assertContains(response, "Проверка QR")
            self.assertContains(response, "/static/cashier/cashier.js")
            self.assertIn("no-store", response["Cache-Control"])

    def test_html_login_rejects_customer_and_accepts_cashier(self):
        response = self.client.post(
            "/cashier/login/",
            {
                "username": "customer",
                "password": "StrongCinema482",
            },
        )
        self.assertContains(response, "Для входа нужна учётная запись")
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(
            "/cashier/login/",
            {
                "username": "cashier",
                "password": "StrongCinema482",
                "next": "https://untrusted.example/",
            },
        )
        self.assertRedirects(response, "/cashier/")

    def test_login_and_logout_require_csrf_and_logout_is_post_only(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(
            browser.post(
                "/cashier/login/",
                {
                    "username": "cashier",
                    "password": "StrongCinema482",
                },
            ).status_code,
            403,
        )
        browser.get("/cashier/login/")
        token = browser.cookies["csrftoken"].value
        self.assertEqual(
            browser.post(
                "/cashier/login/",
                {
                    "username": "cashier",
                    "password": "StrongCinema482",
                    "csrfmiddlewaretoken": token,
                },
            ).status_code,
            302,
        )
        self.assertEqual(browser.get("/cashier/logout/").status_code, 405)
        self.assertEqual(browser.post("/cashier/logout/").status_code, 403)
        token = browser.cookies["csrftoken"].value
        self.assertRedirects(
            browser.post(
                "/cashier/logout/",
                {
                    "csrfmiddlewaretoken": token,
                },
            ),
            "/cashier/login/",
        )
        self.assertNotIn("_auth_user_id", browser.session)

    def test_schedule_excludes_started_and_cancelled_sessions(self):
        self.client.force_login(self.cashier)
        data = self.client.get("/cashier/schedule/").json()
        self.assertEqual([s["id"] for s in data["sessions"]], [self.session.pk])
        self.assertEqual(data["sessions"][0]["base_price"], "300.00")
        self.assertIn("server_time", data)
        type(self.session).objects.filter(pk=self.session.pk).update(is_cancelled=True)
        self.assertEqual(self.client.get("/cashier/schedule/").json()["sessions"], [])
        type(self.session).objects.filter(pk=self.session.pk).update(
            is_cancelled=False, start_datetime=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(self.client.get("/cashier/schedule/").json()["sessions"], [])

    def test_browser_sale_csrf_prices_ticket_files_and_receipt(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.cashier)
        browser.get("/cashier/")
        payload = self.sale_payload("card")
        self.seat.seat_type = "vip"
        self.seat.save()
        no_csrf = browser.post(
            "/api/v1/cashier/sales/", json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(no_csrf.status_code, 403)
        self.assertEqual(Order.objects.count(), 0)
        response = browser.post(
            "/api/v1/cashier/sales/",
            json.dumps(payload),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["total_price"], "450.00")
        self.assertEqual(data["status"], "paid")
        self.assertEqual(data["payment"]["method"], "card")
        self.assertTrue(data["tickets"][0]["qr_payload"])
        order = Order.objects.get(pk=data["id"])
        self.assertIsNone(order.user_id)
        self.assertEqual(order.created_by_id, self.cashier.pk)
        self.assertEqual(order.payment.amount, Decimal("450.00"))
        receipt = browser.get(f"/cashier/receipt/{order.pk}/")
        self.assertContains(receipt, "Распечатать билеты")
        self.assertContains(receipt, "Ряд 1 · Место 1")
        self.assertIn("no-store", receipt["Cache-Control"])
        ticket_id = data["tickets"][0]["id"]
        qr = browser.get(f"/api/v1/tickets/{ticket_id}/download/?export=qr")
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr["Content-Type"], "image/png")
        repeat = browser.post(
            "/api/v1/cashier/sales/",
            json.dumps(payload),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value,
        )
        self.assertEqual(repeat.status_code, 409)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        seat_map = browser.get(f"/api/v1/sessions/{self.session.pk}/seat-map/").json()
        self.assertEqual(
            next(s for s in seat_map["seats"] if s["id"] == self.seat.pk)["status"], "occupied"
        )

    def test_recent_sales_are_own_paid_walk_in_orders(self):
        order = create_cash_sale(self.cashier, **self.sale_payload())
        seats = list(self.hall.seats.all())
        create_cash_sale(self.other_cashier, self.session.pk, [seats[1].pk], "cash")
        create_booking(self.customer, self.session.pk, [seats[2].pk], created_by=self.cashier)
        self.client.force_login(self.cashier)
        response = self.client.get("/cashier/recent-sales/")
        self.assertEqual([o["id"] for o in response.json()["orders"]], [str(order.pk)])
        self.assertIn("no-store", response["Cache-Control"])

    def test_unpaid_receipt_is_not_available(self):
        order = create_booking(self.customer, self.session.pk, [self.seat.pk])
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(f"/cashier/receipt/{order.pk}/").status_code, 404)

    def test_cashier_link_is_discoverable_from_api_and_admin(self):
        self.assertEqual(
            self.client.get("/api/v1/").json()["cashier"],
            "http://testserver" + reverse("cashier:index"),
        )
        self.client.force_login(self.cashier)
        self.assertContains(self.client.get("/admin/"), 'href="/cashier/"')
