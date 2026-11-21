"""Explicit form field boundaries for catalog and identity management."""

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User
from catalog.models import Genre, Hall, Movie, Seat, Session

LABELS = {
    "name": "Название",
    "title": "Название фильма",
    "description": "Описание",
    "duration_minutes": "Длительность, минут",
    "genre": "Жанр",
    "age_limit": "Возраст",
    "poster_image": "Постер JPG/PNG до 5 МБ",
    "is_active": "Активен",
    "rows_count": "Количество рядов",
    "seats_per_row": "Мест в ряду",
    "cleaning_minutes": "Уборка, минут",
    "vip_multiplier": "Коэффициент VIP",
    "movie": "Фильм",
    "hall": "Зал",
    "start_datetime": "Начало сеанса",
    "base_price": "Базовая цена, ₽",
    "seat_type": "Категория места",
    "is_available": "Доступно для продажи",
}


def catalog_form(model, fields):
    """Build narrow ModelForms while keeping domain validation on model instances."""
    return forms.modelform_factory(
        model,
        fields=fields,
        labels=LABELS,
        widgets={
            "start_datetime": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
            )
        },
    )


CATALOG = {
    "movies": (
        Movie,
        "Фильмы",
        catalog_form(
            Movie,
            [
                "title",
                "description",
                "duration_minutes",
                "genre",
                "age_limit",
                "poster_image",
                "is_active",
            ],
        ),
    ),
    "genres": (Genre, "Жанры", catalog_form(Genre, ["name"])),
    "halls": (
        Hall,
        "Залы",
        catalog_form(
            Hall,
            [
                "name",
                "rows_count",
                "seats_per_row",
                "description",
                "cleaning_minutes",
                "vip_multiplier",
                "is_active",
            ],
        ),
    ),
    "sessions": (
        Session,
        "Сеансы",
        catalog_form(Session, ["movie", "hall", "start_datetime", "base_price"]),
    ),
    "seats": (Seat, "Места", catalog_form(Seat, ["seat_type", "is_available"])),
}


class AccountForm(forms.ModelForm):
    """Superuser-only form; privilege flags are not accepted from submitted data."""

    new_password = forms.CharField(
        label="Новый пароль",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Обязателен при создании. Оставьте пустым, чтобы сохранить текущий пароль.",
    )
    confirm_password = forms.CharField(
        label="Повторите пароль", required=False, strip=False, widget=forms.PasswordInput
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "role", "is_active"]
        labels = {"phone": "Телефон", "role": "Роль"}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        if self.instance.is_superuser:
            self.fields["role"].disabled = True
        if self.instance.pk == actor.pk:
            self.fields["is_active"].disabled = True

    def clean(self):
        data = super().clean()
        password = data.get("new_password", "")
        if not self.instance.pk and not password:
            self.add_error("new_password", "Укажите пароль нового пользователя.")
        if password != data.get("confirm_password", ""):
            self.add_error("confirm_password", "Пароли не совпадают.")
        if password:
            candidate = User(
                username=data.get("username", ""),
                email=data.get("email", ""),
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
            )
            try:
                validate_password(password, candidate)
            except ValidationError as exc:
                self.add_error("new_password", exc)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
            self.save_m2m()
        return user


class PeriodForm(forms.Form):
    """Bound the synchronous report period."""

    start = forms.DateField(label="С", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="По", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end"):
            if not 0 <= (data["end"] - data["start"]).days <= 366:
                raise ValidationError("Выберите период от 1 до 367 дней.")
        return data
