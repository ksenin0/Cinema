"""Verify Django Admin uses the same deletion guards as the REST API."""

from django.contrib.admin.sites import site
from django.core.management import call_command
from django.test import TestCase, override_settings

from catalog.models import Movie, Session
from tests.factories import TEST_STORAGES, create_catalog


@override_settings(STORAGES=TEST_STORAGES)
class AdminWorkflowTests(TestCase):
    """Soft deletion must not use the normal protected-FK cascade collector."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Prepare one movie and its future screening."""
        cls.movie, cls.hall, cls.session = create_catalog()

    def test_movie_deletion_preview_has_domain_explanation(self) -> None:
        """Future screenings are shown as deletion blockers before confirmation."""
        _, _, _, protected = site._registry[Movie].get_deleted_objects([self.movie], None)
        self.assertTrue(protected)
        self.assertIn("будущими сеансами", protected[0])

    def test_movie_soft_delete_preserves_cancelled_screening(self) -> None:
        """A cancelled screening does not block archiving its movie through Django Admin."""
        self.session.delete()
        movie_admin = site._registry[Movie]
        _, _, _, protected = movie_admin.get_deleted_objects([self.movie], None)
        self.assertEqual(protected, [])
        movie_admin.delete_queryset(None, Movie.objects.filter(pk=self.movie.pk))
        self.movie.refresh_from_db()
        self.assertFalse(self.movie.is_active)
        self.assertTrue(Session.objects.filter(pk=self.session.pk, is_cancelled=True).exists())

    def test_demo_command_is_repeatable_and_creates_no_accounts(self) -> None:
        """The optional catalog initializer can safely run more than once per day."""
        from io import StringIO

        from accounts.models import User
        from catalog.models import Hall

        call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())
        hall = Hall.objects.get(name="Демонстрационный зал")
        self.assertEqual(hall.seats.count(), 40)
        self.assertEqual(hall.sessions.count(), 3)
        self.assertFalse(User.objects.exists())
