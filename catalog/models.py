"""Cinema catalog and shared hall/scheduling models."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from catalog.validators import validate_poster


class Genre(models.Model):
    """Reusable movie genre dictionary."""

    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        """Return the genre name for admin widgets."""
        return self.name


class Movie(models.Model):
    """Movie card shared by the web backend and future desktop client."""

    title = models.CharField(max_length=200)
    description = models.TextField()
    duration_minutes = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    genre = models.ForeignKey(Genre, on_delete=models.PROTECT, related_name="movies")
    age_limit = models.PositiveSmallIntegerField(
        choices=[(age, f"{age}+") for age in (0, 6, 12, 16, 18)]
    )
    poster_image = models.ImageField(upload_to="posters/%Y/%m/", validators=[validate_poster])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["title", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0), name="movie_positive_duration"
            )
        ]

    def __str__(self) -> str:
        """Return the movie title for administrative lists."""
        return self.title

    def clean(self) -> None:
        """Prevent duration edits that could invalidate already planned sessions."""
        if self.pk:
            original = Movie.objects.get(pk=self.pk)
            if (
                not self.is_active
                and self.sessions.filter(
                    is_cancelled=False, start_datetime__gt=timezone.now()
                ).exists()
            ):
                raise ValidationError("Сначала отмените будущие сеансы фильма.")
            if (
                original.duration_minutes != self.duration_minutes
                and self.sessions.filter(
                    is_cancelled=False, start_datetime__gt=timezone.now()
                ).exists()
            ):
                raise ValidationError(
                    {"duration_minutes": "Сначала отмените будущие сеансы фильма."}
                )

    def save(self, *args: object, **kwargs: object) -> None:
        """Validate movie metadata inside a write transaction before persistence."""
        with transaction.atomic():
            self.full_clean()
            super().save(*args, **kwargs)

    def validate_deletion(self) -> None:
        """Raise ValidationError when the movie is referenced by a future screening."""
        if self.sessions.filter(is_cancelled=False, start_datetime__gt=timezone.now()).exists():
            raise ValidationError("Нельзя удалить фильм с будущими сеансами.")

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict]:
        """Soft-delete the movie; reject removal while future sessions exist."""
        with transaction.atomic():
            self.validate_deletion()
            self.is_active = False
            self.save(update_fields=["is_active"])
        return 0, {}


class Hall(models.Model):
    """Hall dimensions with a generated seat grid and configurable cleaning interval."""

    name = models.CharField(max_length=100, unique=True)
    rows_count = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(50)]
    )
    seats_per_row = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    description = models.TextField(blank=True)
    cleaning_minutes = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(15)]
    )
    vip_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.50"),
        validators=[MinValueValidator(Decimal("1.00"))],
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rows_count__gte=1, seats_per_row__gte=1),
                name="hall_positive_grid",
            ),
            models.CheckConstraint(
                condition=models.Q(cleaning_minutes__gte=15), name="hall_cleaning_minimum"
            ),
            models.CheckConstraint(
                condition=models.Q(vip_multiplier__gte=1), name="hall_vip_minimum"
            ),
        ]

    def __str__(self) -> str:
        """Return the hall name in admin and relation widgets."""
        return self.name

    def clean(self) -> None:
        """Keep existing grid dimensions and planned cleaning intervals stable."""
        if self.pk:
            original = Hall.objects.get(pk=self.pk)
            if (
                not self.is_active
                and self.sessions.filter(
                    is_cancelled=False, end_datetime__gt=timezone.now()
                ).exists()
            ):
                raise ValidationError("Нельзя деактивировать зал с активными сеансами.")
            if (original.rows_count, original.seats_per_row) != (
                self.rows_count,
                self.seats_per_row,
            ):
                raise ValidationError(
                    "Размер существующего зала неизменяем. Создайте новую конфигурацию."
                )
            if (
                original.cleaning_minutes != self.cleaning_minutes
                and self.sessions.filter(
                    is_cancelled=False, start_datetime__gt=timezone.now()
                ).exists()
            ):
                raise ValidationError(
                    "Изменение уборочного интервала требует отмены будущих сеансов."
                )

    def save(self, *args: object, **kwargs: object) -> None:
        """Create a validated hall and its complete numbered seat grid atomically."""
        with transaction.atomic():
            is_new = self.pk is None
            self.full_clean()
            super().save(*args, **kwargs)
            if is_new:
                Seat.objects.bulk_create(
                    [
                        Seat(hall=self, row_number=row_number, seat_number=seat_number)
                        for row_number in range(1, self.rows_count + 1)
                        for seat_number in range(1, self.seats_per_row + 1)
                    ]
                )

    def validate_deletion(self) -> None:
        """Raise ValidationError when an active screening still needs this hall."""
        if self.sessions.filter(is_cancelled=False, end_datetime__gt=timezone.now()).exists():
            raise ValidationError("Зал используется активными сеансами.")

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict]:
        """Deactivate a hall only when it has no active future sessions."""
        with transaction.atomic():
            self.validate_deletion()
            self.is_active = False
            self.save(update_fields=["is_active"])
        return 0, {}


class Seat(models.Model):
    """Physical seat; an aisle is represented by is_available=False."""

    class Type(models.TextChoices):
        STANDARD = "standard", "Стандарт"
        VIP = "vip", "VIP"
        DISABLED = "disabled", "Место для инвалидов"

    hall = models.ForeignKey(Hall, on_delete=models.PROTECT, related_name="seats")
    row_number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    seat_number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    seat_type = models.CharField(max_length=12, choices=Type.choices, default=Type.STANDARD)
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ["row_number", "seat_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["hall", "row_number", "seat_number"], name="unique_hall_seat"
            ),
            models.CheckConstraint(
                condition=models.Q(row_number__gte=1, seat_number__gte=1),
                name="seat_positive_coordinates",
            ),
        ]

    def __str__(self) -> str:
        """Return a human-readable physical seat address."""
        return f"{self.hall}: {self.row_number}/{self.seat_number}"

    def clean(self) -> None:
        """Validate coordinates and prevent moving seats or hiding sold places."""
        if self.hall_id and (
            self.row_number > self.hall.rows_count or self.seat_number > self.hall.seats_per_row
        ):
            raise ValidationError("Место находится за пределами сетки зала.")
        if not self.pk:
            return
        original = Seat.objects.get(pk=self.pk)
        if (original.hall_id, original.row_number, original.seat_number) != (
            self.hall_id,
            self.row_number,
            self.seat_number,
        ):
            raise ValidationError("Координаты существующего места неизменяемы.")
        if (
            original.is_available
            and not self.is_available
            and self.tickets.filter(is_active=True, session__end_datetime__gt=timezone.now())
            .filter(
                models.Q(order__status="paid")
                | models.Q(order__status="pending", order__expires_at__gt=timezone.now())
            )
            .exists()
        ):
            raise ValidationError("Нельзя закрыть место с действующим билетом или бронью.")

    def save(self, *args: object, **kwargs: object) -> None:
        """Persist a validated seat configuration within an atomic write."""
        with transaction.atomic():
            self.full_clean()
            super().save(*args, **kwargs)


class Session(models.Model):
    """Screening with computed end time and cleaning-aware overlap validation."""

    movie = models.ForeignKey(Movie, on_delete=models.PROTECT, related_name="sessions")
    hall = models.ForeignKey(Hall, on_delete=models.PROTECT, related_name="sessions")
    start_datetime = models.DateTimeField(db_index=True)
    end_datetime = models.DateTimeField(editable=False)
    base_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    is_cancelled = models.BooleanField(default=False)

    class Meta:
        ordering = ["start_datetime", "id"]
        indexes = [models.Index(fields=["hall", "start_datetime", "end_datetime"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_datetime__gt=models.F("start_datetime")),
                name="session_positive_interval",
            ),
            models.CheckConstraint(
                condition=models.Q(base_price__gt=0), name="session_positive_price"
            ),
        ]

    def __str__(self) -> str:
        """Return the screening identification for administrative widgets."""
        return f"{self.movie} — {self.start_datetime:%d.%m %H:%M}"

    def clean(self) -> None:
        """Compute the end time and reject unavailable resources or interval conflicts."""
        if not self.movie_id or not self.hall_id or not self.start_datetime:
            return
        self.end_datetime = self.start_datetime + timedelta(minutes=self.movie.duration_minutes)
        if self.is_cancelled:
            return
        if not self.movie.is_active or not self.hall.is_active:
            raise ValidationError("Фильм и зал должны быть активны.")
        cleaning = timedelta(minutes=self.hall.cleaning_minutes)
        if (
            Session.objects.filter(
                hall=self.hall,
                is_cancelled=False,
                start_datetime__lt=self.end_datetime + cleaning,
                end_datetime__gt=self.start_datetime - cleaning,
            )
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError({"start_datetime": "Накладка сеансов с учётом уборки зала."})
        if self.pk:
            original = Session.objects.get(pk=self.pk)
            if original.is_cancelled:
                raise ValidationError("Отменённый сеанс нельзя восстановить.")
            is_changed = any(
                getattr(original, field) != getattr(self, field)
                for field in ("movie_id", "hall_id", "start_datetime")
            )
            if (
                is_changed
                and self.tickets.filter(is_active=True)
                .filter(
                    models.Q(order__status="paid")
                    | models.Q(order__status="pending", order__expires_at__gt=timezone.now())
                )
                .exists()
            ):
                raise ValidationError(
                    "Сеанс с билетами или действующими бронями нельзя переносить."
                )

    def save(self, *args: object, **kwargs: object) -> None:
        """Serialize schedule writes on SQLite and validate before saving."""
        with transaction.atomic():
            if self.movie_id and self.start_datetime:
                self.end_datetime = self.start_datetime + timedelta(
                    minutes=self.movie.duration_minutes
                )
            self.full_clean()
            super().save(*args, **kwargs)

    def validate_deletion(self) -> None:
        """Raise ValidationError when purchased tickets require explicit cancellation."""
        if self.tickets.filter(order__status="paid").exists():
            raise ValidationError("На сеанс уже куплены билеты. Используйте отмену сеанса.")

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict]:
        """Reject deletion of purchased sessions; cancel the remaining screening."""
        from bookings.services import cancel_session

        with transaction.atomic():
            self.validate_deletion()
            cancel_session(self.pk)
        return 0, {}
