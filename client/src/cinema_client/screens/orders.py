"""Order history and electronic tickets with protected downloads."""

import asyncio
from pathlib import Path

import flet as ft

from cinema_client.models import Order, money, show_time
from cinema_client.screens.base import Screen
from cinema_client.theme import (
    ACCENT,
    DANGER,
    SUCCESS,
    TEXT,
    badge,
    empty_state,
    muted,
    panel,
    primary,
    secondary,
    title,
)

ORDER_STATUS = {
    "pending": "Ожидает оплаты",
    "paid": "Оплачен",
    "cancelled": "Отменён",
    "expired": "Бронь истекла",
}


class OrdersScreen(Screen):
    """Keep pending purchases, future tickets, and historical orders in one place."""

    nav_index = 1

    def __init__(self, app: object) -> None:
        """Initialize the active/history filter and order list."""
        super().__init__(app)
        self.orders: list[Order] = []
        self.is_history = False
        self.cards = ft.Column(spacing=16)

    async def load(self) -> None:
        """Fetch current statuses, including any server-expired holds."""
        self.orders = await self.app.api.orders()

    async def filter_orders(self, is_history: bool) -> None:
        """Switch between upcoming purchases and archived/cancelled orders."""
        self.is_history = is_history
        self.app.render()

    async def resume(self, order: Order) -> None:
        """Resume an existing hold without creating another reservation."""
        response = await self.app.api.request("GET", f"sessions/{order.tickets[0].session}/")
        from cinema_client.models import Session

        await self.app.open(
            "seats", {"session": Session.from_json(response.json()), "order": order}
        )

    async def cancel(self, order: Order) -> None:
        """Ask for confirmation before releasing a pending reservation."""

        async def confirmed() -> None:
            """Cancel on the server, then reload the history."""
            await self.app.api.cancel(order.id)
            await self.load()
            self.app.render()

        self.app.confirm(
            "Отменить бронь?", "Выбранные места снова станут доступны другим зрителям.", confirmed
        )

    def card(self, order: Order) -> ft.Control:
        """Describe the screening, its allocated seats, and permitted next actions."""
        if not order.tickets:
            return ft.Container()
        ticket = order.tickets[0]
        color = (
            SUCCESS if order.status == "paid" else ACCENT if order.status == "pending" else DANGER
        )
        controls = [
            ft.Row(
                [
                    badge(ORDER_STATUS.get(order.status, order.status), color),
                    muted(f"Заказ {order.id[:8].upper()}"),
                ],
                wrap=True,
            ),
            title(ticket.movie_title, 22),
            muted(f"{show_time(ticket.start_datetime)} · {ticket.hall_name}", 16),
            ft.Text(
                " · ".join(
                    f"Ряд {item.row_number}, место {item.seat_number}" for item in order.tickets
                ),
                color=TEXT,
            ),
            title(money(order.total_price), 24),
        ]
        if order.status == "pending":
            controls += [
                primary("Продолжить покупку", self.app.event(self.resume, order)),
                ft.TextButton("Отменить бронь", on_click=self.app.event(self.cancel, order)),
            ]
        elif order.status == "paid" and any(item.is_active for item in order.tickets):
            controls.append(
                primary(
                    "Показать билеты",
                    self.app.event(self.app.open, "ticket", order),
                    icon=ft.Icons.QR_CODE_2,
                )
            )
        return panel(ft.Column(controls, spacing=14))

    def build(self) -> ft.Control:
        """Display active orders or archived orders with an explicit empty state."""
        cards = []
        for order in self.orders:
            is_active = order.status in {"pending", "paid"} and any(
                ticket.start_datetime.timestamp() > self.app.now().timestamp()
                for ticket in order.tickets
            )
            if is_active != self.is_history:
                cards.append(self.card(order))
        return self.scroll(
            title("Билеты и заказы"),
            muted("Оплаченные билеты и незавершённые покупки — всегда под рукой.", 16),
            ft.Row(
                [
                    secondary("Предстоящие", self.app.event(self.filter_orders, False)),
                    secondary("История", self.app.event(self.filter_orders, True)),
                    ft.IconButton(
                        ft.Icons.REFRESH,
                        tooltip="Обновить заказы",
                        on_click=self.app.event(self.app.open, "orders"),
                    ),
                ],
                wrap=True,
            ),
            badge("История заказов" if self.is_history else "Предстоящие сеансы"),
            *(
                cards
                or [
                    empty_state(
                        "Здесь пока нет билетов",
                        "Выберите фильм в афише и оформите покупку.",
                        primary("Открыть афишу", self.app.event(self.app.open, "catalog")),
                    )
                ]
            ),
        )


class TicketScreen(Screen):
    """Paid ticket QR codes; never expose an unauthenticated media link."""

    nav_index = 1

    def __init__(self, app: object, order: Order) -> None:
        """Store an order snapshot while loading the latest admission state."""
        super().__init__(app)
        self.order = order
        self.qr_images: dict[str, bytes] = {}

    async def load(self) -> None:
        """Check ownership/status again and fetch QR images using JWT authentication."""
        self.order = await self.app.api.order(self.order.id)

        async def load_qr(ticket: object) -> None:
            """Load one valid ticket's QR bytes."""
            if ticket.is_active and ticket.qr_payload:
                self.qr_images[ticket.id] = await self.app.api.ticket_file(ticket.id, "qr")

        await asyncio.gather(*(load_qr(ticket) for ticket in self.order.tickets))

    async def download(self, ticket_id: str, extension: str) -> None:
        """Use the platform save dialog on desktop/mobile/web, handling cancellation quietly."""
        data = await self.app.api.ticket_file(ticket_id, extension)
        result = await ft.FilePicker().save_file(
            file_name=f"ticket-{ticket_id}.{extension}",
            dialog_title="Сохранить электронный билет",
            src_bytes=data,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=[extension],
        )
        if result and not self.app.page.web and not self.app.page.platform.is_mobile():
            await asyncio.to_thread(Path(result).write_bytes, data)
        if result:
            self.app.notify("Билет сохранён.")
        elif self.app.page.web:
            self.app.notify("Билет передан браузеру для сохранения.")

    def build(self) -> ft.Control:
        """Show each seat as a separate scannable electronic admission ticket."""
        cards = []
        for ticket in self.order.tickets:
            if ticket.id not in self.qr_images:
                cards.append(
                    empty_state("Билет недействителен", "Возможно, заказ или сеанс был отменён.")
                )
                continue
            cards.append(
                panel(
                    ft.Column(
                        [
                            badge(
                                "Вход подтверждён" if ticket.is_checked_in else "Электронный билет",
                                SUCCESS,
                            ),
                            title(ticket.movie_title, 22),
                            muted(f"{show_time(ticket.start_datetime)} · {ticket.hall_name}", 14),
                            title(f"Ряд {ticket.row_number}   ·   Место {ticket.seat_number}", 22),
                            ft.Container(
                                ft.Image(
                                    src=self.qr_images[ticket.id],
                                    width=220,
                                    height=220,
                                    fit=ft.BoxFit.CONTAIN,
                                    semantics_label="QR-код вашего электронного билета",
                                ),
                                padding=12,
                                bgcolor="white",
                                border_radius=12,
                                alignment=ft.Alignment.CENTER,
                            ),
                            muted("Покажите QR-код сотруднику при входе в зал."),
                            ft.Row(
                                [
                                    secondary(
                                        "Сохранить PDF",
                                        self.app.event(self.download, ticket.id, "pdf"),
                                        icon=ft.Icons.DOWNLOAD,
                                    ),
                                    secondary(
                                        "Сохранить PNG",
                                        self.app.event(self.download, ticket.id, "png"),
                                    ),
                                ],
                                wrap=True,
                                run_spacing=10,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=16,
                )
            )
        return self.scroll(
            ft.TextButton(
                "К билетам",
                icon=ft.Icons.ARROW_BACK,
                on_click=self.app.event(self.app.open, "orders"),
            ),
            title("Ваши билеты", 26),
            muted(f"Заказ {self.order.id[:8].upper()} · {money(self.order.total_price)}"),
            *cards,
        )
