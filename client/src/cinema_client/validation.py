"""Local form validation complements, but never replaces, the server's rules."""

import re


def required(values: dict[str, str], names: tuple[str, ...]) -> dict[str, list[str]]:
    """Return field errors for missing mandatory values."""
    return {name: ["Заполните поле."] for name in names if not values.get(name, "").strip()}


def email_error(value: str) -> bool:
    """Check basic mailbox syntax without contacting a real mail server."""
    return len(value) > 254 or not bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]{2,}", value))


def profile_errors(values: dict[str, str]) -> dict[str, list[str]]:
    """Validate editable profile field lengths and email syntax locally."""
    errors = {}
    if email_error(values.get("email", "")):
        errors["email"] = ["Введите адрес вида viewer@example.test."]
    for name, maximum in (("first_name", 150), ("last_name", 150), ("phone", 25)):
        if len(values.get(name, "")) > maximum:
            errors[name] = [f"Допустимо не больше {maximum} символов."]
    return errors


def password_errors(
    values: dict[str, str], name: str = "new_password", confirmation: str = "new_password_confirm"
) -> dict[str, list[str]]:
    """Require the advertised password complexity and matching confirmation."""
    password = values.get(name, "")
    errors = {}
    if len(password) < 8 or not all(
        re.search(pattern, password) for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]")
    ):
        errors[name] = ["От 8 символов: латинские буквы обоих регистров и цифра."]
    if password != values.get(confirmation, ""):
        errors[confirmation] = ["Пароли не совпадают."]
    return errors


def registration_errors(values: dict[str, str]) -> dict[str, list[str]]:
    """Validate registration input before a network request is sent."""
    errors = profile_errors(values) | password_errors(values, "password", "password_confirm")
    errors.update(
        required(
            values, ("username", "first_name", "phone", "email", "password", "password_confirm")
        )
    )
    username = values.get("username", "")
    if len(username) > 150 or not re.fullmatch(r"[\w.@+-]+", username):
        errors["username"] = [
            "Логин: до 150 символов, без пробелов; допустимы буквы, цифры и @ . + - _."
        ]
    return errors
