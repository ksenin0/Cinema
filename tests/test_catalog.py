"""Scheduling and configuration invariants shared by every client."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from bookings.services import create_booking
from catalog.models import Hall, Seat, Session
from catalog.validators import validate_poster
from tests.factories import TEST_STORAGES, create_catalog, create_user


@override_settings(STORAGES=TEST_STORAGES)
class CatalogTests(TestCase):
    """Verify cleaning intervals, immutable coordinates, and image validation."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Build a catalog once for isolated transactional test cases."""
        cls.movie, cls.hall, cls.session = create_catalog()

    def test_grid_generation(self) -> None:
        """A new hall contains every numbered cell exactly once."""
        self.assertEqual(self.hall.seats.count(), 12)
        self.assertTrue(self.hall.seats.filter(row_number=3, seat_number=4).exists())

    def test_overlaps_include_cleaning_in_both_directions(self) -> None:
        """A screening cannot overlap either side of an existing cleaning interval."""
        for start in (
            self.session.end_datetime + timedelta(minutes=19),
            self.session.start_datetime - timedelta(minutes=119),
        ):
            with self.assertRaises(ValidationError):
                Session.objects.create(
                    movie=self.movie, hall=self.hall, start_datetime=start, base_price=300
                )

    def test_exact_cleaning_boundary_is_allowed(self) -> None:
        """A full twenty-minute cleaning interval permits the next screening."""
        later = Session.objects.create(
            movie=self.movie,
            hall=self.hall,
            start_datetime=self.session.end_datetime + timedelta(minutes=20),
            base_price=300,
        )
        self.assertEqual(later.end_datetime - later.start_datetime, timedelta(minutes=100))

    def test_different_halls_can_screen_simultaneously(self) -> None:
        """Time conflicts are scoped to a single physical hall."""
        hall = Hall.objects.create(name="Зал 2", rows_count=1, seats_per_row=1)
        Session.objects.create(
            movie=self.movie, hall=hall, start_datetime=self.session.start_datetime, base_price=200
        )

    def test_invalid_coordinates_and_resize_are_rejected(self) -> None:
        """Physical coordinates and grid dimensions cannot silently change."""
        with self.assertRaises(ValidationError):
            Seat.objects.create(hall=self.hall, row_number=4, seat_number=1)
        self.hall.rows_count = 5
        with self.assertRaises(ValidationError):
            self.hall.save()

    def test_deletion_guards_and_duration_changes(self) -> None:
        """Future sessions protect hall/movie visibility and schedule duration."""
        for obj in (self.movie, self.hall):
            with self.assertRaises(ValidationError):
                obj.delete()
        self.movie.duration_minutes = 200
        with self.assertRaises(ValidationError):
            self.movie.save()

    def test_active_allocation_protects_seat_and_schedule(self) -> None:
        """An active booking prevents hiding its seat or moving its screening."""
        seat = self.hall.seats.first()
        create_booking(create_user(), self.session.pk, [seat.pk])
        seat.is_available = False
        with self.assertRaises(ValidationError):
            seat.save()
        self.session.start_datetime += timedelta(hours=5)
        with self.assertRaises(ValidationError):
            self.session.save()

    def test_fake_image_and_oversized_upload_are_rejected(self) -> None:
        """Extension and MIME claims never replace server-side content checks."""
        with self.assertRaises(ValidationError):
            validate_poster(SimpleUploadedFile("fake.png", b"not an image"))
        with self.assertRaises(ValidationError):
            validate_poster(SimpleUploadedFile("big.png", b"0" * (5 * 1024 * 1024 + 1)))
