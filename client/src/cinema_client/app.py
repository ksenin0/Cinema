"""Application lifecycle, navigation, and guarded asynchronous UI actions."""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

import flet as ft

from cinema_client.api import ApiError, CinemaApi
from cinema_client.models import Movie, ServerClock, Session
from cinema_client.screens.account import (
    AuthScreen,
    PasswordScreen,
    ProfileScreen,
    ResetScreen,
    SettingsScreen,
)
from cinema_client.screens.base import Screen
from cinema_client.screens.catalog import CatalogScreen, MovieScreen
from cinema_client.screens.orders import OrdersScreen, TicketScreen
from cinema_client.screens.seats import SeatsScreen
from cinema_client.theme import (
    ACCENT,
    BACKGROUND,
    BORDER,
    ON_ACCENT,
    SURFACE,
    SURFACE_HIGH,
    TEXT,
    VIP,
    empty_state,
    muted,
    primary,
    title,
)

LOGGER = logging.getLogger(__name__)


class CinemaApp:
    """Per-window controller; transport, screen rendering, and business state stay separate."""

    def __init__(self, page: ft.Page, api: CinemaApi | None = None) -> None:
        """Create a client session and navigation state without loading data synchronously."""
        self.page = page
        default_host = "10.0.2.2" if page.platform == ft.PagePlatform.ANDROID else "127.0.0.1"
        self.api = api or CinemaApi(
            os.environ.get("CINEMA_API_URL", f"http://{default_host}:8000/api/v1/")
        )
        self.clock = ServerClock()
        self.view: Screen | None = None
        self.content = ft.Container(expand=True)
        self.is_loading = False
        self.is_busy = False
        self.is_running = True
        self.poll_task = None
        self.movie_cache: dict[int, Movie] = {}
        self.navigation = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(
                    icon=ft.Icons.LOCAL_MOVIES_OUTLINED,
                    selected_icon=ft.Icons.LOCAL_MOVIES,
                    label="Афиша",
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.CONFIRMATION_NUMBER_OUTLINED,
                    selected_icon=ft.Icons.CONFIRMATION_NUMBER,
                    label="Билеты",
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.PERSON_OUTLINE, selected_icon=ft.Icons.PERSON, label="Профиль"
                ),
            ],
            on_change=self.change_tab,
            bgcolor=BACKGROUND,
            indicator_color=SURFACE_HIGH,
        )

    def now(self) -> object:
        """Return the latest server-anchored time with monotonic elapsed seconds."""
        return self.clock.server_time + timedelta(
            seconds=time.monotonic() - self.clock.monotonic_time
        )

    async def start(self) -> None:
        """Install an adaptive shell, load the catalog, and begin one background polling task."""
        self.page.title = "Кинотеатр · билеты"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(
            use_material3=True,
            color_scheme_seed=ACCENT,
            color_scheme=ft.ColorScheme(
                primary=ACCENT,
                on_primary=ON_ACCENT,
                surface=SURFACE,
                on_surface=TEXT,
                secondary=VIP,
                outline=BORDER,
            ),
        )
        self.page.bgcolor = BACKGROUND
        self.page.padding = 0
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        if not self.page.web and not self.page.platform.is_mobile():
            self.page.window.width, self.page.window.height = 1180, 850
            self.page.window.min_width, self.page.window.min_height = 360, 650
        header = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.LOCAL_MOVIES, color=ACCENT, size=28),
                    title("КИНОТЕАТР", 20),
                    ft.Container(expand=True),
                    ft.IconButton(
                        ft.Icons.SETTINGS_OUTLINED,
                        tooltip="Адрес сервера",
                        on_click=self.event(self.open, "settings"),
                    ),
                ],
                spacing=12,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=12),
        )
        shell = ft.SafeArea(
            ft.Container(
                ft.Column(
                    [
                        header,
                        ft.Container(
                            self.content,
                            padding=ft.Padding.symmetric(horizontal=20, vertical=12),
                            expand=True,
                        ),
                        self.navigation,
                    ],
                    spacing=0,
                    expand=True,
                ),
                width=1120,
                expand=True,
                bgcolor=BACKGROUND,
            ),
            expand=True,
        )
        self.page.add(shell)
        self.page.on_disconnect = self.close
        self.page.on_close = self.close
        self.page.on_resize = self.resize
        await self.open("catalog")
        self.poll_task = self.page.run_task(self.poll)

    def make_screen(self, name: str, payload: object = None) -> Screen:
        """Construct one screen from a small, explicit navigation table."""
        factories = {
            "catalog": lambda: CatalogScreen(self),
            "movie": lambda: MovieScreen(self, payload),
            "seats": lambda: SeatsScreen(self, **payload),
            "orders": lambda: OrdersScreen(self),
            "ticket": lambda: TicketScreen(self, payload),
            "auth": lambda: AuthScreen(self, payload),
            "profile": lambda: ProfileScreen(self),
            "reset": lambda: ResetScreen(self),
            "password": lambda: PasswordScreen(self),
            "settings": lambda: SettingsScreen(self),
        }
        return factories[name]()

    async def open(self, name: str, payload: object = None) -> None:
        """Load a screen without stale requests replacing a newer navigation destination."""
        if name in {"orders", "profile", "password", "ticket"} and not self.api.is_authenticated:
            name, payload = "auth", {"after": (name, payload)}
        if isinstance(self.view, CatalogScreen) and self.view.search_task:
            self.view.search_task.cancel()
        view = self.make_screen(name, payload)
        self.view, self.is_loading = view, True
        self.navigation.selected_index = view.nav_index
        self.content.content = ft.Container(
            ft.ProgressRing(color=ACCENT, width=36, height=36),
            alignment=ft.Alignment.CENTER,
            expand=True,
        )
        self.page.update()
        try:
            await view.load()
        except ApiError as exc:
            if self.view is view:
                self.content.content = empty_state(
                    "Не удалось загрузить данные",
                    exc.message,
                    ft.Column(
                        [
                            primary("Повторить", self.event(self.open, name, payload)),
                            ft.TextButton(
                                "Проверить адрес сервера",
                                on_click=self.event(self.open, "settings"),
                            ),
                            ft.TextButton(
                                "Войти в аккаунт", on_click=self.event(self.open, "auth")
                            ),
                        ]
                    ),
                )
                self.is_loading = False
                self.page.update()
            return
        if self.view is view:
            self.is_loading = False
            self.render()

    def render(self) -> None:
        """Build the current screen only after its data is ready."""
        if self.view and not self.is_loading:
            self.content.content = self.view.build()
            self.page.update()

    async def resize(self, event: object) -> None:
        """Reflow local controls after rotation without triggering new HTTP requests."""
        self.render()

    async def change_tab(self, event: object) -> None:
        """Navigate using the three stable destinations on desktop and mobile."""
        await self.execute(
            self.open, ("catalog", "orders", "profile")[self.navigation.selected_index]
        )

    async def open_movie(self, movie: Movie) -> None:
        """Remember the selected card so a screening has a direct back destination."""
        self.movie_cache[movie.id] = movie
        await self.open("movie", movie)

    async def return_to_movie(self, movie_id: int) -> None:
        """Return from seat selection, fetching the card only when it is not cached."""
        if movie_id not in self.movie_cache:
            data = (await self.api.request("GET", f"movies/{movie_id}/")).json()
            self.movie_cache[movie_id] = Movie.from_json(data)
        await self.open("movie", self.movie_cache[movie_id])

    async def open_seats(self, session: Session) -> None:
        """Enter a fresh seat selection for the given screening."""
        await self.open("seats", {"session": session})

    def event(self, callback: Callable[..., Awaitable], *args: object) -> Callable:
        """Create a real async Flet handler; never return an unawaited coroutine from a lambda."""

        async def handle(event: object = None) -> None:
            """Prevent repeated taps while a user action is still awaiting the server."""
            if self.is_busy:
                return
            self.is_busy = True
            control = getattr(event, "control", None)
            if control is not None:
                control.disabled = True
            self.page.update()
            try:
                await self.execute(callback, *args)
            finally:
                self.is_busy = False
                if control is not None:
                    control.disabled = False
                # Reapply checkout's disabled state after generic busy state restoration.
                if isinstance(self.view, SeatsScreen):
                    self.view.update_countdown()
                self.page.update()

        return handle

    async def execute(self, callback: Callable[..., Awaitable], *args: object) -> None:
        """Show useful error feedback while retaining entered form values."""
        try:
            await callback(*args)
        except ApiError as exc:
            if not self.view or not self.view.display_error(exc):
                self.notify(exc.message)
        except ValueError as exc:
            self.notify(str(exc))
        except Exception:
            LOGGER.exception("Client action failed")
            self.notify("Не удалось выполнить действие. Попробуйте ещё раз.")
        self.page.update()

    def notify(self, message: str) -> None:
        """Show a transient, non-blocking message with readable contrast."""
        self.page.show_dialog(
            ft.SnackBar(
                ft.Text(message, color=TEXT),
                bgcolor=SURFACE_HIGH,
                duration=4500,
                show_close_icon=True,
            )
        )

    async def dismiss_dialog(self, event: object = None) -> None:
        """Close the currently shown confirmation dialog."""
        self.page.pop_dialog()

    def confirm(self, heading: str, description: str, callback: Callable[[], Awaitable]) -> None:
        """Require one explicit confirmation before destructive account/order actions."""

        async def accept() -> None:
            """Dismiss confirmation before performing the actual asynchronous action."""
            self.page.pop_dialog()
            await callback()

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=title(heading, 22),
                content=muted(description, 16),
                actions=[
                    ft.TextButton("Отмена", on_click=self.dismiss_dialog),
                    ft.TextButton("Подтвердить", on_click=self.event(accept)),
                ],
            )
        )

    async def logout(self) -> None:
        """Always clear the local session even when token revocation is temporarily offline."""
        try:
            await self.api.logout()
        except ApiError:
            pass
        self.movie_cache.clear()
        await self.open("catalog")

    async def change_server(self, base_url: str) -> None:
        """Verify a candidate address before replacing the current API dependency."""
        candidate = CinemaApi(base_url)
        try:
            response = await candidate.request("GET", "", auth=False)
            try:
                index = response.json()
            except ValueError as exc:
                raise ApiError("По этому адресу не найден API кинотеатра.") from exc
            if not isinstance(index, dict) or "movies" not in index:
                raise ApiError("По этому адресу не найден API кинотеатра.")
        except (ApiError, ValueError):
            await candidate.close()
            raise
        try:
            await self.api.logout()
        except ApiError:
            pass
        await self.api.close()
        self.api = candidate
        self.movie_cache.clear()
        await self.open("catalog")
        self.notify("Подключение настроено.")

    def poster(self, movie: Movie, height: int) -> ft.Control:
        """Display cached bytes to avoid browser CORS and authenticated-image URL problems."""
        data = self.api.images.get(movie.poster_image)
        fallback = ft.Container(
            ft.Icon(ft.Icons.LOCAL_MOVIES, size=64, color=ACCENT),
            height=height,
            bgcolor=SURFACE_HIGH,
            alignment=ft.Alignment.CENTER,
        )
        return (
            ft.Image(
                src=data,
                height=height,
                width=float("inf"),
                fit=ft.BoxFit.COVER,
                error_content=fallback,
                semantics_label=f"Постер: {movie.title}",
            )
            if data
            else fallback
        )

    async def poll(self) -> None:
        """Tick one visible hold per second and refresh its seat-map every five seconds."""
        counter = 0
        while self.is_running:
            await asyncio.sleep(1)
            counter += 1
            view = self.view
            if not isinstance(view, SeatsScreen) or self.is_busy or self.is_loading:
                continue
            try:
                await view.tick()
                if counter % 5 == 0:
                    await view.refresh()
                if self.view is view:
                    self.page.update()
            except ApiError:
                # Preserve the current selection during a brief outage; user actions show errors.
                view.timer.value = "Нет связи с сервером — обновляем…"
                if self.view is view:
                    self.page.update()

    async def close(self, event: object = None) -> None:
        """Stop background work and release transport resources on window/session shutdown."""
        self.is_running = False
        if self.poll_task:
            self.poll_task.cancel()
        await self.api.close()
