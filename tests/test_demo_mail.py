"""Coursework messages are written locally, even when the address is fictitious."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings

from notifications.models import Notification
from tests.factories import create_user


@override_settings(EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend")
class DemoMailTests(TestCase):
    """Verify the default backend never contacts an SMTP server."""

    def test_fake_email_is_written_locally_without_smtp(self) -> None:
        """A fake mailbox receives a readable local message, with no network calls."""
        user = create_user("demo_mail")
        Notification.objects.create(
            user=user,
            recipient="viewer@example.test",
            subject="Demo password reset",
            body="Demo token: local-only-token",
        )
        with TemporaryDirectory(dir=settings.BASE_DIR, prefix=".test-mail-") as directory:
            with override_settings(EMAIL_FILE_PATH=directory):
                with patch("smtplib.SMTP", side_effect=AssertionError("SMTP is disabled")):
                    call_command("send_notifications", stdout=StringIO())
            messages = list(Path(directory).glob("*.log"))
            self.assertEqual(len(messages), 1)
            message = messages[0].read_text(encoding="utf-8")
            self.assertIn("viewer@example.test", message)
            self.assertIn("local-only-token", message)
        self.assertIsNotNone(Notification.objects.get(user=user).sent_at)
