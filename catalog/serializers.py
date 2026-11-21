"""Catalog resource input/output validation."""

from django.db import transaction
from rest_framework import serializers

from catalog.models import Genre, Hall, Movie, Seat, Session


class GenreSerializer(serializers.ModelSerializer):
    """Genre dictionary resource."""

    class Meta:
        model = Genre
        fields = ["id", "name"]


class MovieSerializer(serializers.ModelSerializer):
    """Movie metadata including a validated poster upload."""

    genre_name = serializers.CharField(source="genre.name", read_only=True)

    class Meta:
        model = Movie
        fields = [
            "id",
            "title",
            "description",
            "duration_minutes",
            "genre",
            "genre_name",
            "age_limit",
            "poster_image",
            "is_active",
        ]

    def validate_is_active(self, value: bool) -> bool:
        """Require the deletion workflow when hiding a movie with future sessions."""
        from django.utils import timezone

        if (
            not value
            and self.instance
            and self.instance.sessions.filter(
                is_cancelled=False, start_datetime__gt=timezone.now()
            ).exists()
        ):
            raise serializers.ValidationError("Сначала отмените будущие сеансы фильма.")
        return value


class HallSerializer(serializers.ModelSerializer):
    """Hall configuration; saving a new hall also creates its physical seat grid."""

    class Meta:
        model = Hall
        fields = [
            "id",
            "name",
            "rows_count",
            "seats_per_row",
            "description",
            "cleaning_minutes",
            "vip_multiplier",
            "is_active",
        ]


class SeatSerializer(serializers.ModelSerializer):
    """Editable seat category and aisle marker with immutable coordinates."""

    class Meta:
        model = Seat
        fields = ["id", "hall", "row_number", "seat_number", "seat_type", "is_available"]
        read_only_fields = ["id", "hall", "row_number", "seat_number"]


class LayoutSeatSerializer(serializers.Serializer):
    """A single cell update in the hall configuration matrix."""

    id = serializers.IntegerField(min_value=1)
    seat_type = serializers.ChoiceField(choices=Seat.Type.choices)
    is_available = serializers.BooleanField()


class HallLayoutSerializer(serializers.Serializer):
    """Validate and apply a bounded list of hall cell updates atomically."""

    seats = LayoutSeatSerializer(many=True, allow_empty=False, max_length=5000)

    @transaction.atomic
    def update(self, instance: Hall, validated_data: dict) -> Hall:
        """Update only cells belonging to this hall; roll back every change on an error."""
        cells = validated_data["seats"]
        seat_ids = [cell["id"] for cell in cells]
        seats = {seat.pk: seat for seat in instance.seats.filter(pk__in=seat_ids)}
        if len(seats) != len(seat_ids) or len(set(seat_ids)) != len(seat_ids):
            raise serializers.ValidationError("Повторяющиеся места или места другого зала.")
        for cell in cells:
            seat = seats[cell["id"]]
            seat.seat_type = cell["seat_type"]
            seat.is_available = cell["is_available"]
            seat.save()
        return instance


class SessionSerializer(serializers.ModelSerializer):
    """Screening schedule with a computed immutable end time."""

    movie_title = serializers.CharField(source="movie.title", read_only=True)
    hall_name = serializers.CharField(source="hall.name", read_only=True)

    class Meta:
        model = Session
        fields = [
            "id",
            "movie",
            "movie_title",
            "hall",
            "hall_name",
            "start_datetime",
            "end_datetime",
            "base_price",
            "is_cancelled",
        ]
        read_only_fields = ["end_datetime", "is_cancelled"]

    def validate_start_datetime(self, value: object) -> object:
        """Prevent creating or rescheduling a screening in the past."""
        from django.utils import timezone

        if value <= timezone.now():
            raise serializers.ValidationError("Укажите время в будущем.")
        return value
