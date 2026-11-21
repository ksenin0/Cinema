"""Read-only financial history; mutations are available only through business operations."""

from django.contrib import admin

from bookings.models import Order, Payment, Ticket


class AccountingAdmin(admin.ModelAdmin):
    """Prevent raw edits which could bypass price, allocation, and payment invariants."""

    def has_add_permission(self, request: object) -> bool:
        """Create accounting records only through the booking services."""
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        """Disallow direct state or price edits, including for superusers."""
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        """Preserve financial history permanently."""
        return False


@admin.register(Order)
class OrderAdmin(AccountingAdmin):
    """Read-only order ledger."""

    list_display = ["id", "user", "total_price", "status", "created_at", "expires_at"]
    list_filter = ["status", "created_at"]


@admin.register(Ticket)
class TicketAdmin(AccountingAdmin):
    """Read-only admission and allocation ledger."""

    list_display = ["id", "session", "seat", "price", "is_active", "is_checked_in"]
    list_filter = ["is_active", "is_checked_in"]


@admin.register(Payment)
class PaymentAdmin(AccountingAdmin):
    """Read-only payments and refund tracking."""

    list_display = ["id", "order", "amount", "method", "status", "created_at"]
    list_filter = ["status", "method"]
