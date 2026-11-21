"""Movie discovery, filtering, and chronological screening selection."""

import asyncio
from collections import defaultdict

import flet as ft

from cinema_client.models import Movie, Session, money, show_time
from cinema_client.screens.base import Screen
from cinema_client.theme import (
    ACCENT,
    BACKGROUND,
    MUTED,
    SURFACE,
    TEXT,
    badge,
    empty_state,
    field,
    muted,
    panel,
    primary,
    secondary,
    title,
)


class CatalogScreen(Screen):
    """Public movie cards with debounced text search and genre filtering."""

    def __init__(self, app: object) -> None:
        """Create stable filter controls so async refreshes do not steal text focus."""
        super().__init__(app)
        self.movies: list[Movie] = []
        self.search = field(
            "Найти фильм", prefix_icon=ft.Icons.SEARCH, on_change=self.search_changed
        )
        self.genre = ft.Dropdown(
            label="Жанр",
            value="",
            on_select=self.filters_changed,
            options=[ft.DropdownOption("", "Все жанры")],
            border_color=MUTED,
            width=float("inf"),
        )
        self.grid = ft.ResponsiveRow(spacing=16, run_spacing=20)
        self.results = ft.Container(content=self.grid)
        self.count = muted("")
        self.search_task: asyncio.Task | None = None
        self.version = 0

    async def load(self) -> None:
        """Load genre options and the first set of movie cards."""
        genres = await self.app.api.collection("genres/")
        self.genre.options += [
            ft.DropdownOption(str(genre["id"]), genre["name"]) for genre in genres
        ]
        await self.reload()

    async def reload(self) -> None:
        """Replace search results only if no newer query superseded this request."""
        self.version += 1
        version = self.version
        movies = await self.app.api.movies(self.search.value.strip(), self.genre.value or "")
        await asyncio.gather(*(self.app.api.poster(movie.poster_image) for movie in movies))
        if version != self.version:
            return
        self.movies = movies
        self.render_results()

    async def search_changed(self, event: object) -> None:
        """Debounce rapid typing and retain only the final server search result."""
        if self.search_task:
            self.search_task.cancel()

        async def search() -> None:
            """Wait briefly before issuing the final query without blocking UI events."""
            await asyncio.sleep(0.35)
            await self.app.execute(self.reload)

        self.search_task = asyncio.create_task(search())

    async def filters_changed(self, event: object) -> None:
        """Reload movies after a genre selection."""
        await self.app.execute(self.reload)

    def render_results(self) -> None:
        """Create poster cards with equal visual hierarchy and an explicit booking action."""
        self.grid.controls = [self.movie_card(movie) for movie in self.movies]
        self.results.content = (
            self.grid
            if self.movies
            else empty_state(
                "Фильмы не найдены", "Попробуйте другое название или выберите все жанры."
            )
        )
        self.count.value = f"В афише: {len(self.movies)}"

    def movie_card(self, movie: Movie) -> ft.Container:
        """Build one adaptive poster card; poster failures use a stable fallback."""
        image = self.app.poster(movie, 250)
        return ft.Container(
            ft.Column(
                [
                    image,
                    ft.Container(
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        badge(f"{movie.age_limit}+"),
                                        muted(f"{movie.duration_minutes} мин"),
                                    ]
                                ),
                                ft.Text(
                                    movie.title,
                                    size=19,
                                    weight=ft.FontWeight.W_600,
                                    color=TEXT,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    tooltip=movie.title,
                                ),
                                muted(movie.genre_name),
                                primary(
                                    "Выбрать сеанс",
                                    self.app.event(self.app.open_movie, movie),
                                    icon=ft.Icons.ARROW_FORWARD,
                                    width=float("inf"),
                                ),
                            ],
                            spacing=12,
                        ),
                        padding=16,
                    ),
                ],
                spacing=0,
            ),
            bgcolor=SURFACE,
            border_radius=16,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            col={"xs": 12, "sm": 6, "md": 4, "lg": 3},
        )

    def build(self) -> ft.Control:
        """Display a restrained cinematic header followed by functional search and cards."""
        self.render_results()
        self.search.col = {"xs": 12, "sm": 8}
        self.genre.col = {"xs": 12, "sm": 4}
        return self.scroll(
            ft.Column(
                [
                    badge("УЧЕБНЫЙ КИНОТЕАТР"),
                    title("Сейчас в кино", 32),
                    muted("Выберите фильм, сеанс и удобные места. Остальное — пара нажатий.", 16),
                ],
                spacing=12,
            ),
            ft.ResponsiveRow([self.search, self.genre], run_spacing=12),
            self.count,
            self.results,
        )


class MovieScreen(Screen):
    """Movie details and date-grouped screening buttons."""

    def __init__(self, app: object, movie: Movie) -> None:
        """Keep the selected card while screening details load asynchronously."""
        super().__init__(app)
        self.movie, self.sessions = movie, []

    async def load(self) -> None:
        """Load only this movie's currently bookable screenings."""
        self.sessions = await self.app.api.sessions(self.movie.id)

    def screening_groups(self) -> list[ft.Control]:
        """Create accessible date groups and descriptive time/price buttons."""
        grouped: dict[str, list[Session]] = defaultdict(list)
        for session in self.sessions:
            if session.start_datetime.timestamp() > self.app.now().timestamp():
                grouped[session.start_datetime.strftime("%d.%m.%Y")].append(session)
        controls: list[ft.Control] = []
        for date, sessions in grouped.items():
            controls.append(
                panel(
                    ft.Column(
                        [
                            title(date, 18),
                            ft.Row(
                                [
                                    secondary(
                                        f"{session.start_datetime:%H:%M} · {session.hall_name}"
                                        f" · от {money(session.base_price)}",
                                        self.app.event(self.app.open_seats, session),
                                        icon=ft.Icons.EVENT_SEAT_OUTLINED,
                                        tooltip=show_time(session.start_datetime),
                                    )
                                    for session in sessions
                                ],
                                wrap=True,
                                spacing=12,
                                run_spacing=12,
                            ),
                        ],
                        spacing=16,
                    )
                )
            )
        return controls or [
            empty_state("Скоро в расписании", "Для этого фильма пока нет доступных сеансов.")
        ]

    def build(self) -> ft.Control:
        """Render movie context and a single clear path to selecting seats."""
        info = ft.Column(
            [
                ft.Row(
                    [
                        badge(f"{self.movie.age_limit}+"),
                        badge(self.movie.genre_name),
                        muted(f"{self.movie.duration_minutes} минут"),
                    ],
                    wrap=True,
                ),
                title(self.movie.title, 32),
                ft.Text(self.movie.description, size=16, color=TEXT, selectable=True),
            ],
            spacing=18,
            col={"xs": 12, "md": 8},
        )
        poster = ft.Container(
            self.app.poster(self.movie, 320),
            col={"xs": 12, "md": 4},
            bgcolor=BACKGROUND,
            border_radius=16,
        )
        return self.scroll(
            ft.TextButton(
                "К афише",
                icon=ft.Icons.ARROW_BACK,
                on_click=self.app.event(self.app.open, "catalog"),
            ),
            ft.ResponsiveRow([poster, info], spacing=24, run_spacing=20),
            ft.Row([ft.Icon(ft.Icons.SCHEDULE, color=ACCENT), title("Выберите сеанс", 24)]),
            *self.screening_groups(),
        )
