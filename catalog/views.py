"""Catalog API for administrators and public listings for future clients."""

from django.db.models import QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from bookings.selectors import get_seat_map
from bookings.services import cancel_session
from catalog.models import Genre, Hall, Movie, Seat, Session
from catalog.serializers import (
    GenreSerializer,
    HallLayoutSerializer,
    HallSerializer,
    MovieSerializer,
    SeatSerializer,
    SessionSerializer,
)
from common.permissions import CatalogPermission, has_role


class GenreViewSet(viewsets.ModelViewSet):
    """Public genre listing and administrator dictionary editing."""

    queryset = Genre.objects.all()
    serializer_class = GenreSerializer
    permission_classes = [CatalogPermission]


class MovieViewSet(viewsets.ModelViewSet):
    """Movie CRUD with soft deletion, text search, and genre filtering."""

    serializer_class = MovieSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self) -> QuerySet:
        """Return visible movies narrowed by optional search and genre parameters."""
        queryset = Movie.objects.select_related("genre")
        if not has_role(self.request.user, "admin", "cashier"):
            queryset = queryset.filter(is_active=True)
        search = self.request.query_params.get("search")
        if search:
            # SQLite LIKE only folds ASCII. The small cinema catalog needs Unicode search.
            normalized_search = search.strip().casefold()
            matching_ids = [
                movie_id
                for movie_id, title in queryset.values_list("id", "title")
                if normalized_search in title.casefold()
            ]
            queryset = queryset.filter(pk__in=matching_ids)
        genre = self.request.query_params.get("genre")
        if genre:
            if not genre.isdecimal():
                raise ValidationError({"genre": "Ожидается числовой идентификатор."})
            queryset = queryset.filter(genre_id=int(genre))
        return queryset


class HallViewSet(viewsets.ModelViewSet):
    """Hall administration and physical matrix configuration endpoints."""

    serializer_class = HallSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self) -> QuerySet:
        """Expose active halls publicly and all halls to personnel."""
        queryset = Hall.objects.all()
        return (
            queryset
            if has_role(self.request.user, "admin", "cashier")
            else queryset.filter(is_active=True)
        )

    @action(detail=True, methods=["get", "patch"])
    def layout(self, request: Request, pk: str | None = None) -> Response:
        """Read a hall's cells or atomically update categories and aisle markers."""
        hall = self.get_object()
        if request.method == "PATCH":
            serializer = HallLayoutSerializer(hall, data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(
            {
                "hall": HallSerializer(hall).data,
                "seats": SeatSerializer(hall.seats.all(), many=True).data,
            }
        )


class SeatViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Edit a generated physical seat; arbitrary seat creation/deletion is excluded."""

    queryset = Seat.objects.select_related("hall")
    serializer_class = SeatSerializer
    permission_classes = [CatalogPermission]


class SessionViewSet(viewsets.ModelViewSet):
    """Conflict-checked schedule, real-time seat availability, and cancellation."""

    serializer_class = SessionSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self) -> QuerySet:
        """Filter screenings by movie, hall and local date, ordered chronologically."""
        queryset = Session.objects.select_related("movie", "hall")
        if not has_role(self.request.user, "admin", "cashier"):
            queryset = queryset.filter(
                is_cancelled=False,
                start_datetime__gt=timezone.now(),
                movie__is_active=True,
                hall__is_active=True,
            )
        for field in ("movie", "hall"):
            value = self.request.query_params.get(field)
            if value:
                if not value.isdecimal():
                    raise ValidationError({field: "Ожидается числовой идентификатор."})
                queryset = queryset.filter(**{f"{field}_id": int(value)})
        date = self.request.query_params.get("date")
        if date:
            try:
                parsed = parse_date(date)
            except ValueError:
                parsed = None
            if parsed is None:
                raise ValidationError({"date": "Ожидается дата YYYY-MM-DD."})
            queryset = queryset.filter(start_datetime__date=parsed)
        return queryset

    @action(detail=True, methods=["get"], url_path="seat-map")
    def seat_map(self, request: Request, pk: str | None = None) -> Response:
        """Return physical layout, prices, server time, and current allocation state."""
        response = Response(get_seat_map(self.get_object(), request.user))
        response["Cache-Control"] = "no-store"
        return response

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Cancel a screening through the booking use case, including notifications."""
        session = cancel_session(self.get_object().pk)
        return Response(self.get_serializer(session).data)
