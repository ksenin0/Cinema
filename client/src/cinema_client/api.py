"""Async HTTP boundary with token refresh, typed results, and consistent error messages."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from cinema_client.models import Movie, Order, SeatMap, Session


@dataclass
class ApiError(Exception):
    """A user-facing API/network error; field errors can be attached to form controls."""

    message: str
    status_code: int = 0
    errors: dict = field(default_factory=dict)

    def __str__(self) -> str:
        """Return the message for notifications and log messages."""
        return self.message


def normalize_url(value: str) -> str:
    """Validate the configured server URL and normalize its API suffix."""
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Введите адрес вида http://127.0.0.1:8000/api/v1/.")
    if not parsed.path or parsed.path == "/":
        value += "/api/v1"
    elif parsed.path == "/api":
        value += "/v1"
    elif parsed.path != "/api/v1":
        raise ValueError("Адрес API должен заканчиваться на /api/v1/.")
    return value + "/"


class CinemaApi:
    """One per-window HTTP client; credentials live only in memory and never in SQLite."""

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Configure timeout and optional test transport without contacting the server."""
        self.base_url = normalize_url(base_url)
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=15,
            transport=transport,
            trust_env=False,
            follow_redirects=True,
        )
        self.access_token = ""
        self.refresh_token = ""
        self.profile: dict | None = None
        self.images: dict[str, bytes] = {}
        self.refresh_lock = asyncio.Lock()
        self.image_limit = asyncio.Semaphore(4)
        self.on_session_expired: Callable[[], None] | None = None

    @property
    def is_authenticated(self) -> bool:
        """Report whether this window has authenticated tokens and a loaded profile."""
        return bool(self.access_token and self.profile)

    async def close(self) -> None:
        """Release network connections when the app window/session closes."""
        await self.http.aclose()

    def clear_session(self) -> None:
        """Forget both tokens and personal profile data locally."""
        self.access_token = self.refresh_token = ""
        self.profile = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        retry_auth: bool = True,
        **kwargs: object,
    ) -> httpx.Response:
        """Send one request, refresh once on 401, and convert known failures to ApiError."""
        current_token = self.access_token
        headers = {"Authorization": f"Bearer {current_token}"} if auth and current_token else {}
        try:
            response = await self.http.request(method, path, headers=headers, **kwargs)
        except httpx.RequestError as exc:
            raise ApiError(
                "Нет связи с кинотеатром. Проверьте адрес сервера и подключение."
            ) from exc
        if response.status_code == 401 and auth and retry_auth and self.refresh_token:
            await self._refresh(current_token)
            return await self.request(method, path, auth=auth, retry_auth=False, **kwargs)
        if response.is_error:
            self._raise_error(response)
        return response

    def _raise_error(self, response: httpx.Response) -> None:
        """Translate server error envelopes without showing raw HTML or stack traces."""
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if response.status_code == 401:
            self.clear_session()
            if self.on_session_expired:
                self.on_session_expired()
        message = data.get("message") or data.get("detail") or "Не удалось выполнить запрос."
        if response.status_code == 404:
            message = "Данные не найдены. Обновите страницу; проверьте также адрес сервера."
        if response.status_code >= 500:
            message = "Сервер временно недоступен. Попробуйте ещё раз."
        errors = data.get("errors", data)
        raise ApiError(
            str(message), response.status_code, errors if isinstance(errors, dict) else {}
        )

    async def _refresh(self, previous_token: str) -> None:
        """Rotate a refresh token once even when several requests expire simultaneously."""
        async with self.refresh_lock:
            if self.access_token != previous_token:
                if not self.access_token:
                    raise ApiError("Сессия завершена. Войдите заново.", 401)
                return
            response = await self.request(
                "POST",
                "auth/token/refresh/",
                auth=False,
                retry_auth=False,
                json={"refresh": self.refresh_token},
            )
            data = response.json()
            self.access_token = data["access"]
            self.refresh_token = data.get("refresh", self.refresh_token)

    async def login(self, username: str, password: str) -> dict:
        """Authenticate with JWT and load the profile; forget partial credentials on failure."""
        response = await self.request(
            "POST",
            "auth/token/",
            auth=False,
            json={"username": username.strip(), "password": password},
        )
        data = response.json()
        self.access_token, self.refresh_token = data["access"], data["refresh"]
        try:
            self.profile = (await self.request("GET", "auth/me/")).json()
        except ApiError:
            self.clear_session()
            raise
        return self.profile

    async def logout(self) -> None:
        """Revoke the refresh token when possible, always clearing local credentials."""
        try:
            if self.refresh_token:
                await self.request(
                    "POST", "auth/token/logout/", auth=False, json={"refresh": self.refresh_token}
                )
        finally:
            self.clear_session()

    async def collection(self, path: str, **params: object) -> list[dict]:
        """Follow Django pagination, accepting only same-origin continuation links."""
        results, visited = [], set()
        while path:
            url = self.http.base_url.join(path)
            if (url.scheme, url.host, url.port) != (
                self.http.base_url.scheme,
                self.http.base_url.host,
                self.http.base_url.port,
            ) or str(url) in visited:
                raise ApiError("Некорректная ссылка следующей страницы от сервера.")
            visited.add(str(url))
            response = await self.request("GET", str(url), params=params or None)
            data = response.json()
            if isinstance(data, list):
                return results + data
            results.extend(data["results"])
            path, params = data.get("next"), {}
        return results

    async def movies(self, search: str = "", genre: str = "") -> list[Movie]:
        """Read public movie cards with optional search and genre filters."""
        params = {key: value for key, value in {"search": search, "genre": genre}.items() if value}
        return [Movie.from_json(data) for data in await self.collection("movies/", **params)]

    async def sessions(self, movie_id: int) -> list[Session]:
        """Read a movie's available screenings in chronological order."""
        return [
            Session.from_json(data)
            for data in await self.collection("sessions/", movie=movie_id)
            if not data["is_cancelled"]
        ]

    async def seat_map(self, session_id: int) -> SeatMap:
        """Fetch live seat availability and server time without caching."""
        return SeatMap.from_json(
            (await self.request("GET", f"sessions/{session_id}/seat-map/")).json()
        )

    async def orders(self) -> list[Order]:
        """Read accessible order history, including expired/cancelled reservations."""
        return [Order.from_json(data) for data in await self.collection("orders/")]

    async def order(self, order_id: str) -> Order:
        """Read one current order snapshot."""
        return Order.from_json((await self.request("GET", f"orders/{order_id}/")).json())

    async def reserve(self, session_id: int, seat_ids: set[int]) -> Order:
        """Reserve selected seats; never send client-calculated monetary values."""
        response = await self.request(
            "POST", "orders/", json={"session_id": session_id, "seat_ids": sorted(seat_ids)}
        )
        return Order.from_json(response.json())

    async def pay(self, order_id: str) -> Order:
        """Simulate successful online payment with an empty request body."""
        return Order.from_json(
            (await self.request("POST", f"orders/{order_id}/online-payment/", json={})).json()
        )

    async def cancel(self, order_id: str) -> Order:
        """Cancel an accessible unpaid reservation through the server use case."""
        return Order.from_json(
            (await self.request("POST", f"orders/{order_id}/cancel/", json={})).json()
        )

    async def ticket_file(self, ticket_id: str, extension: str) -> bytes:
        """Download a protected PNG, QR, or PDF with the current access token."""
        return (
            await self.request(
                "GET", f"tickets/{ticket_id}/download/", params={"export": extension}
            )
        ).content

    async def poster(self, url: str) -> bytes | None:
        """Cache poster bytes in memory; a missing poster never prevents buying tickets."""
        if not url:
            return None
        if url not in self.images:
            async with self.image_limit:
                try:
                    response = await self.request("GET", url, auth=False)
                    self.images[url] = response.content
                except ApiError:
                    return None
        return self.images[url]
