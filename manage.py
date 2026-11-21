"""Django command entry point."""

import os
import sys


def main() -> None:
    """Run the Django command supplied in sys.argv; propagate command errors."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
