"""Account application configuration."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Connect role synchronization and role permission setup."""

    name = "accounts"

    def ready(self) -> None:
        """Load signal receivers after the application registry is initialized."""
        from accounts import signals  # noqa: F401
