"""Typed API read models and client-only seat selection state."""

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal


def parse_datetime(value: str) -> datetime:
    """Parse an ISO API timestamp and require an explicit timezone."""
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result


def money(amount: Decimal) -> str:
    """Return a readable ruble amount without losing monetary precision."""
    return f"{amount:,.2f}".replace(",", " ").replace(".00", "") + " ₽"


def show_time(value: datetime) -> str:
    """Display the screening's server-provided local timezone, independent of device timezone."""
    return value.strftime("%d.%m.%Y · %H:%M")


@dataclass(frozen=True)
class Movie:
    """Public movie card returned by the catalog API."""

    id: int
    title: str
    description: str
    duration_minutes: int
    genre_name: str
    age_limit: int
    poster_image: str

    @classmethod
    def from_json(cls, data: dict) -> "Movie":
        """Construct a movie from the server contract, ignoring unrelated metadata."""
        return cls(**{name: data[name] for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Session:
    """A screening and its base price."""

    id: int
    movie: int
    movie_title: str
    hall_name: str
    start_datetime: datetime
    end_datetime: datetime
    base_price: Decimal
    is_cancelled: bool

    @classmethod
    def from_json(cls, data: dict) -> "Session":
        """Parse screening timestamps and decimal price."""
        return cls(
            id=data["id"],
            movie=data["movie"],
            movie_title=data["movie_title"],
            hall_name=data["hall_name"],
            start_datetime=parse_datetime(data["start_datetime"]),
            end_datetime=parse_datetime(data["end_datetime"]),
            base_price=Decimal(data["base_price"]),
            is_cancelled=data["is_cancelled"],
        )


@dataclass(frozen=True)
class Seat:
    """A physical cell and its current allocation state."""

    id: int
    row_number: int
    seat_number: int
    seat_type: str
    status: str
    price: Decimal

    @classmethod
    def from_json(cls, data: dict) -> "Seat":
        """Construct one seat cell, preserving the server's computed price."""
        return cls(
            id=data["id"],
            row_number=data["row_number"],
            seat_number=data["seat_number"],
            seat_type=data["seat_type"],
            status=data["status"],
            price=Decimal(data["price"]),
        )


@dataclass(frozen=True)
class SeatMap:
    """Hall geometry plus a server timestamp used for accurate hold countdowns."""

    session_id: int
    rows_count: int
    seats_per_row: int
    server_time: datetime
    seats: list[Seat]

    @classmethod
    def from_json(cls, data: dict) -> "SeatMap":
        """Parse a real-time matrix response."""
        return cls(
            session_id=data["session_id"],
            rows_count=data["rows_count"],
            seats_per_row=data["seats_per_row"],
            server_time=parse_datetime(data["server_time"]),
            seats=[Seat.from_json(seat) for seat in data["seats"]],
        )


@dataclass(frozen=True)
class Ticket:
    """Owned ticket details; the QR payload is absent until the order is paid."""

    id: str
    session: int
    seat: int
    movie_title: str
    hall_name: str
    start_datetime: datetime
    row_number: int
    seat_number: int
    price: Decimal
    is_active: bool
    is_checked_in: bool
    qr_payload: str | None

    @classmethod
    def from_json(cls, data: dict) -> "Ticket":
        """Parse ticket data and its server-calculated price."""
        values = {name: data[name] for name in cls.__dataclass_fields__}
        values.update(
            start_datetime=parse_datetime(data["start_datetime"]), price=Decimal(data["price"])
        )
        return cls(**values)


@dataclass(frozen=True)
class Order:
    """Order snapshot received after reservation, payment, cancellation, or history lookup."""

    id: str
    total_price: Decimal
    status: str
    expires_at: datetime
    tickets: list[Ticket]

    @classmethod
    def from_json(cls, data: dict) -> "Order":
        """Parse one order and its immutable ticket prices."""
        return cls(
            id=data["id"],
            total_price=Decimal(data["total_price"]),
            status=data["status"],
            expires_at=parse_datetime(data["expires_at"]),
            tickets=[Ticket.from_json(ticket) for ticket in data["tickets"]],
        )


@dataclass
class SeatSelection:
    """Pure UI selection logic; the server remains the final allocation authority."""

    selected_ids: set[int] = field(default_factory=set)

    def toggle(self, seat: Seat) -> None:
        """Toggle an available seat; reject unavailable seats and groups over twenty."""
        if seat.id in self.selected_ids:
            self.selected_ids.remove(seat.id)
        elif seat.status != "free":
            raise ValueError("Это место уже недоступно. Обновите схему.")
        elif len(self.selected_ids) >= 20:
            raise ValueError("В одном заказе можно выбрать до 20 мест.")
        else:
            self.selected_ids.add(seat.id)

    def reconcile(self, seats: list[Seat]) -> bool:
        """Drop selections taken by another visitor; return whether any selection changed."""
        previous = set(self.selected_ids)
        self.selected_ids.intersection_update(seat.id for seat in seats if seat.status == "free")
        return previous != self.selected_ids

    def total(self, seats: list[Seat]) -> Decimal:
        """Calculate a preview total using exact decimal values supplied by the server."""
        return sum((seat.price for seat in seats if seat.id in self.selected_ids), Decimal("0.00"))


@dataclass
class ServerClock:
    """Monotonic clock anchored to server time, resistant to a misconfigured device clock."""

    server_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    monotonic_time: float = field(default_factory=time.monotonic)

    def synchronize(self, server_time: datetime) -> None:
        """Anchor the clock when a fresh seat-map response arrives."""
        self.server_time, self.monotonic_time = server_time, time.monotonic()

    def remaining(self, deadline: datetime) -> int:
        """Return remaining whole seconds, clamped to zero after expiration."""
        now = self.server_time + timedelta(seconds=time.monotonic() - self.monotonic_time)
        return max(0, math.ceil((deadline - now).total_seconds()))
