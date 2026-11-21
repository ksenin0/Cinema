"""Live seat matrix, booking countdown, and credential-free demo checkout."""

import flet as ft

from cinema_client.api import ApiError
from cinema_client.models import Order, Seat, SeatMap, SeatSelection, Session, money, show_time
from cinema_client.screens.base import Screen
from cinema_client.theme import (
    ACCENT,
    BORDER,
    DANGER,
    MUTED,
    ON_ACCENT,
    SUCCESS,
    SURFACE_HIGH,
    VIP,
    badge,
    muted,
    panel,
    primary,
    title,
)

SEAT_TYPES = {"standard": "Стандарт", "vip": "VIP", "disabled": "Доступное место"}
SEAT_STATES = {
    "free": "Свободно",
    "held": "На удержании",
    "selected": "В вашей брони",
    "occupied": "Занято",
    "unavailable": "Недоступно",
}


class SeatsScreen(Screen):
    """Own live screen state separately from the network and pure selection model."""

    def __init__(
        self,
        app: object,
        session: Session,
        order: Order | None = None,
        selection: SeatSelection | None = None,
    ) -> None:
        """Create controls once, preserving selection across login and seat-map polling."""
        super().__init__(app)
        self.session, self.order = session, order
        self.selection = selection or SeatSelection()
        self.matrix: SeatMap | None = None
        self.grid = ft.Container()
        self.selected_text = muted("Выберите места на схеме")
        self.amount = title("0 ₽", 26)
        self.timer = ft.Text(color=ACCENT, size=16, weight=ft.FontWeight.W_600)
        self.pay_button = primary(
            "Продолжить",
            self.app.event(self.checkout),
            icon=ft.Icons.ARROW_FORWARD,
            width=float("inf"),
        )
        self.edit_button = ft.TextButton("Изменить места", on_click=self.app.event(self.release))
        self.selection_list = ft.Dropdown(
            label="Выбрать место из списка",
            enable_search=True,
            options=[],
            on_select=self.select_from_list,
            border_color=BORDER,
        )
        self.expiration_checked = False

    async def load(self) -> None:
        """Synchronize the matrix and restore a pending order's selected seats."""
        await self.refresh()
        if self.order:
            self.selection.selected_ids = {ticket.seat for ticket in self.order.tickets}

    async def refresh(self) -> None:
        """Poll availability and release UI selections taken by another visitor."""
        matrix = await self.app.api.seat_map(self.session.id)
        self.matrix = matrix
        self.app.clock.synchronize(matrix.server_time)
        if not self.order:
            if self.selection.reconcile(matrix.seats):
                self.app.notify("Часть выбранных мест уже занята. Выберите другие.")
        self.refresh_controls()

    async def select_from_list(self, event: object) -> None:
        """Provide a keyboard/screen-reader alternative to panning a large physical matrix."""
        if self.selection_list.value and self.matrix:
            seat = next(
                seat for seat in self.matrix.seats if seat.id == int(self.selection_list.value)
            )
            await self.app.execute(self.toggle, seat)
            self.selection_list.value = None
            self.app.page.update()

    async def toggle(self, seat: Seat) -> None:
        """Change an unreserved selection; held orders must be released before editing."""
        if self.order:
            self.app.notify("Сначала нажмите «Изменить места», чтобы снять текущую бронь.")
            return
        self.selection.toggle(seat)
        self.refresh_controls()

    def seat_button(self, seat: Seat) -> ft.Control:
        """Build a labelled 48-pixel native button; status never relies on color alone."""
        is_selected = seat.id in self.selection.selected_ids
        color = VIP if seat.seat_type == "vip" else SUCCESS
        if seat.status in {"occupied", "unavailable"}:
            color = MUTED
        elif seat.status in {"held", "selected"}:
            color = DANGER
        if is_selected:
            color = ACCENT
        label = str(seat.seat_number)
        if is_selected:
            label = "✓ " + label
        elif seat.seat_type == "vip":
            label += " V"
        elif seat.seat_type == "disabled":
            label += " Д"
        tooltip = (
            f"Ряд {seat.row_number}, место {seat.seat_number}. "
            f"{SEAT_TYPES[seat.seat_type]}. {money(seat.price)}. "
            f"{'Выбрано' if is_selected else SEAT_STATES[seat.status]}."
        )
        return ft.OutlinedButton(
            label,
            width=48,
            height=48,
            tooltip=tooltip,
            disabled=bool(self.order) or seat.status != "free",
            on_click=self.app.event(self.toggle, seat),
            style=ft.ButtonStyle(
                padding=0,
                color=ON_ACCENT if is_selected else color,
                bgcolor=ACCENT if is_selected else SURFACE_HIGH,
                side=ft.BorderSide(2 if is_selected else 1, color),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

    def build_grid(self) -> ft.Control:
        """Preserve physical rows and seat numbers, with horizontal pan only inside the map."""
        if not self.matrix:
            return ft.ProgressRing()
        rows = []
        for row_number in range(1, self.matrix.rows_count + 1):
            cells = [ft.Container(ft.Text(str(row_number), color=MUTED), width=28)]
            cells += [
                self.seat_button(seat)
                for seat in self.matrix.seats
                if seat.row_number == row_number
            ]
            rows.append(ft.Row(cells, spacing=6, tight=True))
        return ft.Row([ft.Column(rows, spacing=8)], scroll=ft.ScrollMode.AUTO)

    def refresh_controls(self) -> None:
        """Update only matrix and checkout controls, retaining focus in other app areas."""
        if not self.matrix:
            return
        self.grid.content = self.build_grid()
        self.selection_list.options = [
            ft.DropdownOption(
                str(seat.id),
                f"Ряд {seat.row_number}, место {seat.seat_number}"
                f" · {SEAT_TYPES[seat.seat_type]} · {money(seat.price)}",
            )
            for seat in self.matrix.seats
            if seat.status == "free"
        ]
        self.selection_list.disabled = self.order is not None
        selected = [seat for seat in self.matrix.seats if seat.id in self.selection.selected_ids]
        self.selected_text.value = (
            " · ".join(f"Ряд {seat.row_number}, место {seat.seat_number}" for seat in selected)
            if selected
            else "Выберите места на схеме"
        )
        self.amount.value = money(
            self.order.total_price if self.order else self.selection.total(self.matrix.seats)
        )
        self.edit_button.visible = self.order is not None
        self.update_countdown()

    def update_countdown(self) -> None:
        """Show the server-anchored deadline and disable payment when the hold expires."""
        seconds = self.app.clock.remaining(self.order.expires_at) if self.order else 0
        self.timer.visible = self.order is not None
        self.timer.value = (
            f"Бронь: {seconds // 60:02d}:{seconds % 60:02d}" if seconds else "Срок брони истёк"
        )
        self.pay_button.content = "Оплатить · демо" if self.order else "Продолжить"
        self.pay_button.disabled = not self.selection.selected_ids or (
            self.order is not None and seconds <= 0
        )

    async def tick(self) -> None:
        """Refresh the timer and reload an expired order only once."""
        self.update_countdown()
        if (
            self.order
            and self.app.clock.remaining(self.order.expires_at) <= 0
            and not self.expiration_checked
        ):
            self.expiration_checked = True
            await self.app.api.order(self.order.id)
            self.order = None
            self.selection.selected_ids.clear()
            await self.refresh()
            self.app.notify("Время бронирования закончилось. Выберите места заново.")

    async def checkout(self) -> None:
        """Reserve first, then simulate payment on the next explicit click."""
        if not self.app.api.is_authenticated:
            await self.app.open(
                "auth", {"after": ("seats", {"session": self.session, "selection": self.selection})}
            )
            return
        if self.order:
            paid = await self.app.api.pay(self.order.id)
            self.app.notify("Готово! Ваши билеты оформлены.")
            await self.app.open("ticket", paid)
            return
        try:
            self.order = await self.app.api.reserve(self.session.id, self.selection.selected_ids)
        except ApiError as exc:
            if exc.status_code == 409:
                await self.refresh()
            raise
        self.expiration_checked = False
        await self.refresh()

    async def release(self) -> None:
        """Release the pending order before allowing edits to its selected seats."""
        if self.order:
            await self.app.api.cancel(self.order.id)
        self.order = None
        self.expiration_checked = False
        await self.refresh()

    def build(self) -> ft.Control:
        """Keep the primary checkout action visible beneath the scrollable seat matrix."""
        self.refresh_controls()
        legend = ft.Row(
            [
                badge("Свободно", SUCCESS),
                badge("VIP · V", VIP),
                badge("Выбрано · ✓", ACCENT),
                badge("Занято", MUTED),
                badge("Бронь", DANGER),
            ],
            wrap=True,
            spacing=8,
            run_spacing=8,
        )
        content = self.scroll(
            ft.TextButton(
                "К сеансам",
                icon=ft.Icons.ARROW_BACK,
                on_click=self.app.event(self.app.return_to_movie, self.session.movie),
            ),
            title(self.session.movie_title),
            muted(f"{show_time(self.session.start_datetime)} · {self.session.hall_name}", 16),
            ft.Container(
                ft.Text("Э К Р А Н", color=MUTED, text_align=ft.TextAlign.CENTER),
                alignment=ft.Alignment.CENTER,
                padding=12,
                bgcolor=SURFACE_HIGH,
                border_radius=24,
            ),
            self.grid,
            muted("Номера слева — ряды. Большую схему можно прокрутить вбок."),
            legend,
            self.selection_list,
        )
        checkout_content = ft.Column(
            [
                self.selected_text,
                ft.Row(
                    [self.amount, self.timer],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    wrap=True,
                ),
                self.pay_button,
                ft.Row([self.edit_button, muted("Без списания денег")], wrap=True),
            ],
            spacing=10,
        )
        width, height = getattr(self.app.page, "width", 0), getattr(self.app.page, "height", 0)
        if width and height and width > height and height < 600:
            checkout_content = ft.Row(
                [
                    ft.Column(
                        [self.selected_text, self.amount, self.timer], expand=True, spacing=4
                    ),
                    ft.Column([self.pay_button, self.edit_button], width=220, spacing=4),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        checkout = panel(checkout_content, padding=12)
        return ft.Column([content, checkout], expand=True, spacing=12)
