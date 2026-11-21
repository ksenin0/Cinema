"""Password policy required by the technical specification."""

import re

from django.core.exceptions import ValidationError


class PasswordComplexityValidator:
    """Require eight characters, Latin upper/lower letters, and a digit."""

    def validate(self, password: str, user: object = None) -> None:
        """Validate password strength; raise ValidationError on a policy violation."""
        if len(password) < 8 or not all(
            re.search(pattern, password) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]")
        ):
            raise ValidationError(self.get_help_text(), code="password_complexity")

    def get_help_text(self) -> str:
        """Return a user-facing explanation of the password rules."""
        return "Пароль: минимум 8 символов, латинские буквы обоих регистров и цифра."
