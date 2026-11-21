"""Replaceable price calculation policy (no client-supplied monetary values)."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from catalog.models import Seat, Session


class PricePolicy(Protocol):
    """Small interface for seat pricing strategies."""

    def calculate(self, session: Session, seat: Seat) -> Decimal:
        """Return the price for a physical seat at the given screening."""
        ...


class StandardPricePolicy:
    """Use the session price, with the hall's multiplier for VIP seats."""

    def calculate(self, session: Session, seat: Seat) -> Decimal:
        """Return a two-decimal monetary amount using commercial rounding."""
        multiplier = session.hall.vip_multiplier if seat.seat_type == Seat.Type.VIP else Decimal(1)
        return (session.base_price * multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
