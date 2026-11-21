"""Create optional demonstration catalog data without adding predefined credentials."""

from datetime import timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from catalog.models import Genre, Hall, Movie, Seat, Session


class Command(BaseCommand):
    """Initialize one demo hall, one movie, and three screenings tomorrow."""

    help = "Создать демонстрационный каталог без учётных записей и паролей."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        """Create missing demo data; repeated execution on the same day is idempotent."""
        genre, _ = Genre.objects.get_or_create(name="Фантастика")
        hall, _ = Hall.objects.get_or_create(
            name="Демонстрационный зал",
            defaults={
                "rows_count": 5,
                "seats_per_row": 8,
                "description": "5 рядов, последний ряд VIP.",
            },
        )
        hall.seats.filter(row_number=5).update(seat_type=Seat.Type.VIP)
        movie = Movie.objects.filter(title="Демонстрационный фильм").first()
        if movie is None:
            poster = Image.new("RGB", (600, 900), "#14213d")
            ImageDraw.Draw(poster).text((150, 420), "CINEMA DEMO", fill="white", font_size=40)
            output = BytesIO()
            poster.save(output, format="PNG")
            movie = Movie.objects.create(
                title="Демонстрационный фильм",
                description="Пример карточки фильма для проверки системы.",
                duration_minutes=100,
                genre=genre,
                age_limit=12,
                poster_image=ContentFile(output.getvalue(), name="demo-poster.png"),
            )
        tomorrow = timezone.localtime().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        for offset in (0, 3, 6):
            Session.objects.get_or_create(
                hall=hall,
                start_datetime=tomorrow + timedelta(hours=offset),
                defaults={"movie": movie, "base_price": "350.00"},
            )
        self.stdout.write(self.style.SUCCESS("Демонстрационные данные готовы."))
