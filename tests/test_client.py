"""Client state, transport and control-construction tests without a Flutter installation."""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import flet as ft
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client" / "src"))

from cinema_client.api import ApiError, CinemaApi, normalize_url  # noqa: E402
from cinema_client.app import CinemaApp  # noqa: E402
from cinema_client.models import Movie, Order, Seat, SeatSelection, ServerClock, Session  # noqa: E402
from cinema_client.validation import password_errors, registration_errors  # noqa: E402


class ClientStateTests(TestCase):
    """Pure state rules do not depend on Flet controls or Django business implementations."""

    def test_selection_uses_decimal_and_reconciles_lost_seats(self) -> None:
        """A newly occupied seat is removed while other selections keep their exact prices."""
        seats = [
            Seat(1, 1, 1, "standard", "free", Decimal("0.10")),
            Seat(2, 1, 2, "vip", "free", Decimal("0.20")),
        ]
        selection = SeatSelection()
        for seat in seats:
            selection.toggle(seat)
        self.assertEqual(selection.total(seats), Decimal("0.30"))
        occupied = Seat(1, 1, 1, "standard", "occupied", Decimal("0.10"))
        self.assertTrue(selection.reconcile([occupied, seats[1]]))
        self.assertEqual(selection.selected_ids, {2})
        with self.assertRaises(ValueError):
            selection.toggle(occupied)

    def test_twenty_seat_limit_and_deselection(self) -> None:
        """UI limits match the booking API while still permitting a selected seat to be removed."""
        selection = SeatSelection(set(range(1, 21)))
        with self.assertRaises(ValueError):
            selection.toggle(Seat(21, 1, 21, "standard", "free", Decimal(1)))
        selection.toggle(Seat(1, 1, 1, "standard", "free", Decimal(1)))
        self.assertEqual(len(selection.selected_ids), 19)

    def test_countdown_uses_server_time_and_monotonic_elapsed(self) -> None:
        """Changing device wall-clock time never extends the server's hold deadline."""
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        clock = ServerClock(now, 100)
        with patch("cinema_client.models.time.monotonic", return_value=110):
            self.assertEqual(clock.remaining(now + timedelta(minutes=10)), 590)
        with patch("cinema_client.models.time.monotonic", return_value=900):
            self.assertEqual(clock.remaining(now + timedelta(minutes=10)), 0)

    def test_server_address_normalization_and_rejection(self) -> None:
        """Accept common local/LAN entry addresses and reject credentials or wrong API paths."""
        self.assertEqual(normalize_url("http://localhost:8000"), "http://localhost:8000/api/v1/")
        self.assertEqual(
            normalize_url("http://192.168.1.5:8000/api/"), "http://192.168.1.5:8000/api/v1/"
        )
        for value in (
            "localhost:8000",
            "http://user:secret@localhost",
            "http://localhost/admin/",
            "http://localhost/?x=1",
        ):
            with self.assertRaises(ValueError):
                normalize_url(value)

    def test_registration_validates_fake_email_and_password_before_request(self) -> None:
        """Accept fictitious mailboxes; reject malformed fields and weak passwords."""
        values = {
            "username": "viewer",
            "first_name": "Имя",
            "phone": "12345",
            "email": "viewer@example.test",
            "password": "CinemaStrong482",
            "password_confirm": "CinemaStrong482",
        }
        self.assertEqual(registration_errors(values), {})
        errors = registration_errors(
            {**values, "email": "wrong", "username": "bad name", "password": "weak"}
        )
        self.assertIn("email", errors)
        self.assertIn("username", errors)
        self.assertIn("password", errors)
        self.assertIn("password_confirm", errors)

    def test_password_confirmation_keeps_significant_whitespace(self) -> None:
        """Local validation does not silently trim or alter password text."""
        self.assertEqual(
            password_errors(
                {"new_password": " CinemaStrong482 ", "new_password_confirm": " CinemaStrong482 "}
            ),
            {},
        )


class ClientTransportTests(IsolatedAsyncioTestCase):
    """Exercise HTTP semantics, auth races, timeouts and error translation."""

    async def test_concurrent_401_requests_refresh_only_once(self) -> None:
        """Rotating refresh tokens are not spent twice by simultaneous API calls."""
        refreshes = 0

        async def handle(request: httpx.Request) -> httpx.Response:
            """Simulate one expired access token and a rotating refresh endpoint."""
            nonlocal refreshes
            if request.url.path.endswith("/token/refresh/"):
                refreshes += 1
                await asyncio.sleep(0.01)
                return httpx.Response(200, json={"access": "new-access", "refresh": "new-refresh"})
            if request.headers.get("Authorization") == "Bearer old-access":
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, json={"ok": True})

        api = CinemaApi("http://server/api/v1/", httpx.MockTransport(handle))
        api.access_token, api.refresh_token = "old-access", "old-refresh"
        try:
            responses = await asyncio.gather(
                api.request("GET", "orders/"), api.request("GET", "tickets/")
            )
            self.assertTrue(all(response.status_code == 200 for response in responses))
            self.assertEqual(refreshes, 1)
            self.assertEqual(api.refresh_token, "new-refresh")
        finally:
            await api.close()

    async def test_field_errors_remain_available_to_forms(self) -> None:
        """A server validation envelope retains its field mapping and friendly message."""
        api = CinemaApi(
            "http://server",
            httpx.MockTransport(
                lambda request: httpx.Response(
                    400,
                    json={"message": "Проверьте поля", "errors": {"email": ["Уже используется"]}},
                )
            ),
        )
        try:
            with self.assertRaises(ApiError) as caught:
                await api.request("POST", "auth/register/", json={})
            self.assertEqual(caught.exception.errors["email"], ["Уже используется"])
        finally:
            await api.close()

    async def test_logout_clears_tokens_even_offline(self) -> None:
        """Local credentials are forgotten even when server-side revocation cannot be reached."""

        def offline(request: httpx.Request) -> httpx.Response:
            """Represent a failed network connection."""
            raise httpx.ConnectError("offline", request=request)

        api = CinemaApi("http://server", httpx.MockTransport(offline))
        api.access_token, api.refresh_token, api.profile = "access", "refresh", {"id": 1}
        try:
            with self.assertRaises(ApiError):
                await api.logout()
            self.assertFalse(api.is_authenticated)
            self.assertEqual(api.refresh_token, "")
        finally:
            await api.close()

    async def test_pagination_and_rejection_of_external_continuations(self) -> None:
        """Follow valid pagination but never send credentials to a foreign continuation URL."""
        requested = []

        def handle(request: httpx.Request) -> httpx.Response:
            """Serve two pages followed by an intentionally invalid continuation."""
            requested.append(str(request.url))
            if request.url.params.get("page"):
                return httpx.Response(200, json={"results": [{"id": 2}], "next": None})
            return httpx.Response(
                200, json={"results": [{"id": 1}], "next": "http://server/api/v1/movies/?page=2"}
            )

        api = CinemaApi("http://server", httpx.MockTransport(handle))
        try:
            self.assertEqual(await api.collection("movies/"), [{"id": 1}, {"id": 2}])
        finally:
            await api.close()
        api = CinemaApi(
            "http://server",
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"results": [], "next": "http://elsewhere/api/v1/movies/"}
                )
            ),
        )
        try:
            with self.assertRaises(ApiError):
                await api.collection("movies/")
        finally:
            await api.close()


class FakePage:
    """A minimal page surface for detecting invalid Flet controls without a GUI process."""

    platform = ft.PagePlatform.WINDOWS
    web = False
    window = SimpleNamespace()

    def __init__(self) -> None:
        """Keep rendered controls/dialogs for assertions."""
        self.controls, self.dialogs = [], []

    def update(self) -> None:
        """Do nothing; actual Flutter rendering is covered by visual smoke checks."""

    def add(self, *controls: object) -> None:
        """Collect shell controls."""
        self.controls.extend(controls)

    def show_dialog(self, dialog: object) -> None:
        """Collect transient overlays."""
        self.dialogs.append(dialog)

    def pop_dialog(self) -> None:
        """Dismiss the last overlay."""
        self.dialogs.pop()

    def run_task(self, callback: object) -> None:
        """Do not start a perpetual background poller in control construction tests."""


class ClientScreenTests(IsolatedAsyncioTestCase):
    """Build every screen using realistic contract data and execute the booking controls."""

    async def test_every_screen_builds_with_current_flet_api(self) -> None:
        """Catch API-renamed controls, invalid properties, and missing fields before GUI launch."""
        start = datetime.now(timezone.utc) + timedelta(days=1)
        movie = {
            "id": 1,
            "title": "Фильм",
            "description": "Описание",
            "duration_minutes": 100,
            "genre_name": "Драма",
            "age_limit": 12,
            "poster_image": "",
        }
        session = {
            "id": 1,
            "movie": 1,
            "movie_title": "Фильм",
            "hall_name": "Зал",
            "base_price": "300.00",
            "start_datetime": start.isoformat(),
            "end_datetime": (start + timedelta(minutes=100)).isoformat(),
            "is_cancelled": False,
        }
        ticket = {
            "id": "ticket",
            "session": 1,
            "seat": 1,
            "movie_title": "Фильм",
            "hall_name": "Зал",
            "start_datetime": start.isoformat(),
            "row_number": 1,
            "seat_number": 1,
            "price": "300.00",
            "is_active": True,
            "is_checked_in": False,
            "qr_payload": "signed",
        }
        order = {
            "id": "order",
            "total_price": "300.00",
            "status": "paid",
            "expires_at": start.isoformat(),
            "tickets": [ticket],
        }

        def handle(request: httpx.Request) -> httpx.Response:
            """Provide the smallest real contract for each screen's data loader."""
            path = request.url.path
            if "seat-map" in path:
                return httpx.Response(
                    200,
                    json={
                        "session_id": 1,
                        "rows_count": 1,
                        "seats_per_row": 1,
                        "server_time": datetime.now(timezone.utc).isoformat(),
                        "seats": [
                            {
                                "id": 1,
                                "row_number": 1,
                                "seat_number": 1,
                                "seat_type": "standard",
                                "status": "free",
                                "price": "300.00",
                            }
                        ],
                    },
                )
            if "download" in path:
                return httpx.Response(200, content=b"mock-png")
            if "auth/me" in path:
                return httpx.Response(
                    200, json={"id": 1, "username": "viewer", "email": "viewer@example.test"}
                )
            if path.endswith("orders/order/"):
                return httpx.Response(200, json=order)
            results = (
                [movie]
                if "movies" in path
                else [session]
                if "sessions" in path
                else [order]
                if "orders" in path
                else []
            )
            return httpx.Response(200, json={"results": results, "next": None})

        api = CinemaApi("http://server", httpx.MockTransport(handle))
        api.access_token, api.profile = "token", {"id": 1}
        app = CinemaApp(FakePage(), api)
        try:
            await app.start()
            for name, payload in (
                ("catalog", None),
                ("movie", Movie.from_json(movie)),
                ("seats", {"session": Session.from_json(session)}),
                ("orders", None),
                ("ticket", Order.from_json(order)),
                ("auth", None),
                ("auth", {"mode": "register"}),
                ("reset", None),
                ("profile", None),
                ("password", None),
                ("settings", None),
            ):
                await app.open(name, payload)
                self.assertIsInstance(app.content.content, ft.Control, name)
                self.assertNotIn("Не удалось", str(app.content.content), name)
        finally:
            await app.close()

    async def test_desktop_save_dialog_writes_downloaded_ticket_bytes(self) -> None:
        """Flet's desktop save dialog returns a path; the application must write the file itself."""
        from cinema_client.screens.orders import TicketScreen

        api = SimpleNamespace(ticket_file=AsyncMock(return_value=b"%PDF-demo"))
        app = SimpleNamespace(api=api, page=FakePage(), notify=lambda message: None)
        screen = TicketScreen(app, None)
        with TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1], prefix=".test-save-"
        ) as directory:
            target = Path(directory) / "ticket.pdf"
            picker = SimpleNamespace(save_file=AsyncMock(return_value=str(target)))
            with patch("cinema_client.screens.orders.ft.FilePicker", return_value=picker):
                await screen.download("ticket", "pdf")
            self.assertEqual(target.read_bytes(), b"%PDF-demo")
