"""Small, deterministic test fixture builders."""

from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from accounts.models import User
from catalog.models import Genre, Hall, Movie, Session

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def poster_file() -> SimpleUploadedFile:
    """Return a real tiny PNG for exercising upload validation."""
    buffer = BytesIO()
    Image.new("RGB", (16, 16), "navy").save(buffer, format="PNG")
    return SimpleUploadedFile("poster.png", buffer.getvalue(), content_type="image/png")


def create_catalog() -> tuple[Movie, Hall, Session]:
    """Create a three-row hall, a movie, and a future screening."""
    genre = Genre.objects.create(name="Фантастика")
    movie = Movie.objects.create(
        title="Тестовый фильм",
        description="Описание фильма",
        duration_minutes=100,
        genre=genre,
        age_limit=12,
        poster_image=poster_file(),
    )
    hall = Hall.objects.create(name="Зал 1", rows_count=3, seats_per_row=4)
    session = Session.objects.create(
        movie=movie,
        hall=hall,
        start_datetime=timezone.now() + timedelta(days=1),
        base_price="300.00",
    )
    return movie, hall, session


def create_user(username: str = "client", role: str = "client") -> User:
    """Create an identity with a known password for authentication tests."""
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password="StrongCinema482", role=role
    )
