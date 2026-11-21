"""Run the actual client transport against the actual Django ASGI application."""

import sys
from pathlib import Path

import httpx
from asgiref.sync import async_to_sync
from django.core.asgi import get_asgi_application
from django.test import TransactionTestCase, override_settings

from tests.factories import TEST_STORAGES, create_catalog, create_user

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client" / "src"))
from cinema_client.api import CinemaApi  # noqa: E402
from cinema_client.app import CinemaApp  # noqa: E402

from tests.test_client import FakePage  # noqa: E402


@override_settings(
    STORAGES=TEST_STORAGES, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class ClientApiIntegrationTests(TransactionTestCase):
    """A complete customer purchase uses exactly the production client and API code paths."""

    def test_login_reservation_demo_payment_ticket_download_and_history(self) -> None:
        """Exercise the complete desktop/mobile customer flow without sockets or fake API data."""
        movie, hall, session = create_catalog()
        create_user()

        async def purchase() -> None:
            """Call real Django routes using an in-process ASGI HTTP transport."""
            api = CinemaApi(
                "http://testserver/api/v1/", httpx.ASGITransport(app=get_asgi_application())
            )
            try:
                await api.login("client", "StrongCinema482")
                movies = await api.movies()
                self.assertEqual(movies[0].id, movie.pk)
                self.assertEqual((await api.sessions(movie.pk))[0].id, session.pk)
                matrix = await api.seat_map(session.pk)
                order = await api.reserve(session.pk, {matrix.seats[0].id})
                self.assertEqual(order.status, "pending")
                self.assertIsNone(order.tickets[0].qr_payload)
                paid = await api.pay(order.id)
                self.assertEqual(paid.status, "paid")
                self.assertTrue(paid.tickets[0].qr_payload)
                self.assertTrue(
                    (await api.ticket_file(paid.tickets[0].id, "pdf")).startswith(b"%PDF")
                )
                self.assertTrue(
                    (await api.ticket_file(paid.tickets[0].id, "qr")).startswith(b"\x89PNG")
                )
                self.assertEqual((await api.orders())[0].id, order.id)
                self.assertEqual((await api.seat_map(session.pk)).seats[0].status, "occupied")
                await api.logout()
                self.assertFalse(api.is_authenticated)
            finally:
                await api.close()

        async_to_sync(purchase)()

    def test_registration_screen_submits_to_real_api_and_opens_profile(self) -> None:
        """The Flet registration action creates a real client and resumes navigation."""

        async def register() -> None:
            """Submit a registration screen through the production transport."""
            api = CinemaApi(
                "http://testserver/api/v1/", httpx.ASGITransport(app=get_asgi_application())
            )
            app = CinemaApp(FakePage(), api)
            try:
                await app.open("auth", {"mode": "register"})
                values = {
                    "username": "new_viewer",
                    "first_name": "Зритель",
                    "last_name": "",
                    "email": "new_viewer@example.test",
                    "phone": "12345",
                    "password": "CinemaStrong482",
                    "password_confirm": "CinemaStrong482",
                }
                for name, value in values.items():
                    app.view.fields[name].value = value
                await app.view.submit()
                self.assertTrue(api.is_authenticated)
                self.assertEqual(api.profile["username"], "new_viewer")
                self.assertEqual(app.view.fields["email"].value, "new_viewer@example.test")
            finally:
                await app.close()

        async_to_sync(register)()
