"""Django Admin catalog with validated saves and guarded deletion workflows."""

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet

from bookings.services import cancel_session
from catalog.models import Genre, Hall, Movie, Seat, Session


class GuardedDeleteAdmin(admin.ModelAdmin):
    """Call model deletion hooks for bulk deletion instead of bypassing soft deletion."""

    def get_deleted_objects(self, objs: object, request: object) -> tuple:
        """Preview soft deletion using domain guards instead of Django's cascade collector."""
        objects = list(objs)
        protected = []
        for obj in objects:
            try:
                obj.validate_deletion()
            except ValidationError as exc:
                protected.extend(exc.messages)
        return (
            [str(obj) for obj in objects],
            {str(self.model._meta.verbose_name_plural): len(objects)},
            set(),
            protected,
        )

    @transaction.atomic
    def delete_queryset(self, request: object, queryset: QuerySet) -> None:
        """Apply each model's guarded soft-deletion operation in the admin transaction."""
        for obj in queryset:
            obj.delete()

    def delete_model(self, request: object, obj: object) -> None:
        """Apply the model's guarded soft-deletion operation."""
        obj.delete()


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    """Genre reference data editor."""

    search_fields = ["name"]


@admin.register(Movie)
class MovieAdmin(GuardedDeleteAdmin):
    """Movie card editor with archive filters."""

    list_display = ["title", "genre", "duration_minutes", "age_limit", "is_active"]
    list_filter = ["genre", "age_limit", "is_active"]
    search_fields = ["title"]


@admin.register(Hall)
class HallAdmin(GuardedDeleteAdmin):
    """Hall dimensions and default price policy editor."""

    list_display = ["name", "rows_count", "seats_per_row", "cleaning_minutes", "is_active"]

    def get_readonly_fields(self, request: object, obj: Hall | None = None) -> list[str]:
        """Freeze dimensions after the physical seat grid has been generated."""
        return ["rows_count", "seats_per_row"] if obj else []


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    """Generated seat category and aisle editing."""

    list_display = ["hall", "row_number", "seat_number", "seat_type", "is_available"]
    list_filter = ["hall", "seat_type", "is_available"]
    readonly_fields = ["hall", "row_number", "seat_number"]

    def has_add_permission(self, request: object) -> bool:
        """Seats are generated with the hall, never added individually."""
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        """Use availability markers instead of deleting physical seat history."""
        return False


@admin.register(Session)
class SessionAdmin(GuardedDeleteAdmin):
    """Chronological schedule editor with explicit cancellation workflow."""

    list_display = ["movie", "hall", "start_datetime", "end_datetime", "base_price", "is_cancelled"]
    list_filter = ["hall", "is_cancelled", "start_datetime"]
    date_hierarchy = "start_datetime"
    readonly_fields = ["end_datetime", "is_cancelled"]
    actions = ["cancel_selected_sessions"]

    @admin.action(
        description="Отменить сеансы и запросить возврат оплаченных заказов", permissions=["change"]
    )
    def cancel_selected_sessions(self, request: object, queryset: QuerySet) -> None:
        """Cancel screenings using the same use case as the HTTP API."""
        if not self.has_change_permission(request):
            return
        for session in queryset:
            try:
                cancel_session(session.pk)
            except ValidationError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
