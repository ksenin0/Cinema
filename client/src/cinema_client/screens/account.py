"""Authentication, registration, recovery and account settings."""

import flet as ft

from cinema_client.api import ApiError
from cinema_client.screens.base import Screen
from cinema_client.theme import DANGER, badge, field, muted, panel, primary, secondary, title
from cinema_client.validation import (
    email_error,
    password_errors,
    profile_errors,
    registration_errors,
    required,
)


class AuthScreen(Screen):
    """Login/registration flow that can resume an interrupted seat selection."""

    nav_index = 2

    def __init__(self, app: object, options: dict | None = None) -> None:
        """Initialize stable form controls and the post-login destination."""
        super().__init__(app)
        self.options = options or {}
        self.mode = self.options.get("mode", "login")
        self.fields = {"username": field("Логин"), "password": field("Пароль", password=True)}
        if self.mode == "register":
            self.fields.update(
                {
                    "password_confirm": field("Повторите пароль", password=True),
                    "first_name": field("Имя"),
                    "last_name": field("Фамилия (необязательно)"),
                    "email": field(
                        "Почта",
                        hint_text="viewer@example.test",
                        keyboard_type=ft.KeyboardType.EMAIL,
                    ),
                    "phone": field("Телефон", keyboard_type=ft.KeyboardType.PHONE),
                }
            )
        self.fields["password"].on_submit = self.app.event(self.submit)

    async def switch(self, mode: str) -> None:
        """Switch auth mode without discarding the intended booking destination."""
        await self.app.open("auth", {**self.options, "mode": mode})

    async def submit(self) -> None:
        """Validate required inputs, register if needed, sign in, and resume the last flow."""
        self.clear_errors()
        values = self.values()
        errors = (
            registration_errors(values)
            if self.mode == "register"
            else required(values, ("username", "password"))
        )
        if not self.validate(errors):
            return
        if self.mode == "register":
            await self.app.api.request("POST", "auth/register/", auth=False, json=values)
        await self.app.api.login(values["username"], values["password"])
        # Forget passwords as soon as they have served their purpose.
        for control in self.fields.values():
            if control.password:
                control.value = ""
        screen, payload = self.options.get("after", ("profile", None))
        await self.app.open(screen, payload)

    def build(self) -> ft.Control:
        """Keep entry forms compact, explicit, and usable with an on-screen keyboard."""
        is_register = self.mode == "register"
        return self.scroll(
            badge("ВАШ ЛИЧНЫЙ КИНОТЕАТР"),
            title("Создать аккаунт" if is_register else "С возвращением"),
            muted("Сохраните билеты и продолжите покупку с любого устройства.", 16),
            panel(
                ft.Column(
                    [
                        *self.fields.values(),
                        self.error_text,
                        muted("Пароль: от 8 символов, латинские буквы обоих регистров и цифра.")
                        if is_register
                        else ft.Container(),
                        primary(
                            "Зарегистрироваться" if is_register else "Войти",
                            self.app.event(self.submit),
                            width=float("inf"),
                        ),
                        ft.TextButton(
                            "Уже есть аккаунт? Войти"
                            if is_register
                            else "Нет аккаунта? Зарегистрироваться",
                            on_click=self.app.event(
                                self.switch, "login" if is_register else "register"
                            ),
                        ),
                        ft.TextButton(
                            "Забыли пароль?", on_click=self.app.event(self.app.open, "reset")
                        ),
                    ],
                    spacing=16,
                )
            ),
            muted("Учебный режим: укажите вымышленную почту, например viewer@example.test."),
            secondary("Продолжить без входа", self.app.event(self.app.open, "catalog")),
        )


class ResetScreen(Screen):
    """Request a local recovery email and consume its one-time code."""

    nav_index = 2

    def __init__(self, app: object) -> None:
        """Initialize email and reset-code fields separately."""
        super().__init__(app)
        self.fields = {
            "email": field("Почта аккаунта", hint_text="viewer@example.test"),
            "uid": field("Код пользователя из письма"),
            "token": field("Одноразовый токен"),
            "new_password": field("Новый пароль", password=True),
            "new_password_confirm": field("Повторите новый пароль", password=True),
        }

    async def request_code(self) -> None:
        """Queue the same generic recovery response for known and unknown addresses."""
        self.clear_errors()
        if email_error(self.fields["email"].value.strip()):
            self.validate({"email": ["Введите адрес вида viewer@example.test."]})
            return
        await self.app.api.request(
            "POST",
            "auth/password/reset/",
            auth=False,
            json={"email": self.fields["email"].value.strip()},
        )
        self.app.notify("Если аккаунт существует, инструкция подготовлена в учебной почте.")

    async def confirm(self) -> None:
        """Replace the password using the code copied from the local demo message."""
        self.clear_errors()
        if not self.validate(
            password_errors(self.values()) | required(self.values(), ("uid", "token"))
        ):
            return
        await self.app.api.request(
            "POST",
            "auth/password/reset/confirm/",
            auth=False,
            json={name: value for name, value in self.values().items() if name != "email"},
        )
        self.app.notify("Пароль изменён. Войдите с новым паролем.")
        await self.app.open("auth")

    def build(self) -> ft.Control:
        """Present recovery as two explicit steps with a path back to login."""
        return self.scroll(
            title("Восстановление пароля"),
            muted("В учебном режиме письмо сохраняется на компьютере с сервером.", 16),
            panel(
                ft.Column(
                    [
                        title("1. Получите инструкцию", 20),
                        self.fields["email"],
                        primary("Подготовить письмо", self.app.event(self.request_code)),
                    ],
                    spacing=16,
                )
            ),
            panel(
                ft.Column(
                    [
                        title("2. Введите данные из письма", 20),
                        *(control for name, control in self.fields.items() if name != "email"),
                        self.error_text,
                        primary("Сменить пароль", self.app.event(self.confirm)),
                    ],
                    spacing=16,
                )
            ),
            ft.TextButton("Вернуться ко входу", on_click=self.app.event(self.app.open, "auth")),
        )


class ProfileScreen(Screen):
    """Safe profile editing, password change, logout, and confirmed deactivation."""

    nav_index = 2

    async def load(self) -> None:
        """Refresh the current profile before editing."""
        profile = (await self.app.api.request("GET", "auth/me/")).json()
        self.app.api.profile = profile
        labels = {"first_name": "Имя", "last_name": "Фамилия", "email": "Почта", "phone": "Телефон"}
        self.fields = {
            name: field(label, value=profile.get(name, "")) for name, label in labels.items()
        }

    async def save(self) -> None:
        """Update only the allowed profile fields; roles remain controlled by the server."""
        self.clear_errors()
        if not self.validate(profile_errors(self.values())):
            return
        self.app.api.profile = (
            await self.app.api.request("PATCH", "auth/me/", json=self.values())
        ).json()
        self.app.notify("Данные сохранены.")

    async def logout(self) -> None:
        """Confirm before revoking tokens and clearing profile data."""
        self.app.confirm("Выйти из аккаунта?", "Ваши билеты останутся в аккаунте.", self.app.logout)

    async def deactivate(self) -> None:
        """Request the current password in a confirmation dialog before anonymization."""
        password = field("Текущий пароль", password=True)
        error_text = ft.Text(color=DANGER, visible=False)

        async def confirm() -> None:
            """Keep validation errors inside the confirmation dialog until success."""
            try:
                await self.app.api.request(
                    "DELETE", "auth/me/", json={"current_password": password.value}
                )
            except ApiError as exc:
                error_text.value, error_text.visible = (
                    "Неверный пароль или операция недоступна.",
                    True,
                )
                self.app.page.update()
                if exc.status_code >= 500:
                    self.app.notify(exc.message)
                return
            self.app.page.pop_dialog()
            self.app.api.clear_session()
            await self.app.open("catalog")
            self.app.notify("Аккаунт деактивирован.")

        dialog = ft.AlertDialog(
            modal=True,
            title=title("Деактивировать аккаунт?", 22),
            content=ft.Column(
                [
                    muted(
                        "Контактные данные будут удалены. История платежей сохранится обезличенно."
                    ),
                    password,
                    error_text,
                ],
                tight=True,
                width=380,
            ),
            actions=[
                ft.TextButton("Отмена", on_click=self.app.dismiss_dialog),
                ft.TextButton("Деактивировать", on_click=self.app.event(confirm)),
            ],
        )
        self.app.page.show_dialog(dialog)

    def build(self) -> ft.Control:
        """Separate ordinary profile editing from explicit account lifecycle actions."""
        profile = self.app.api.profile or {}
        return self.scroll(
            title("Личный кабинет"),
            badge(f"@{profile.get('username', '')}"),
            panel(
                ft.Column(
                    [
                        *self.fields.values(),
                        self.error_text,
                        primary("Сохранить изменения", self.app.event(self.save)),
                    ],
                    spacing=16,
                )
            ),
            secondary(
                "Изменить пароль",
                self.app.event(self.app.open, "password"),
                icon=ft.Icons.LOCK_OUTLINE,
            ),
            secondary("Выйти из аккаунта", self.app.event(self.logout), icon=ft.Icons.LOGOUT),
            ft.TextButton("Деактивировать аккаунт", on_click=self.app.event(self.deactivate)),
            muted("Покупки в этом приложении демонстрационные. Платёжные данные не запрашиваются."),
        )


class PasswordScreen(Screen):
    """Password replacement with the current secret and confirmation."""

    nav_index = 2

    def __init__(self, app: object) -> None:
        """Create password-only fields, each supporting paste and visibility toggling."""
        super().__init__(app)
        self.fields = {
            name: field(label, password=True)
            for name, label in (
                ("current_password", "Текущий пароль"),
                ("new_password", "Новый пароль"),
                ("new_password_confirm", "Повторите новый пароль"),
            )
        }

    async def submit(self) -> None:
        """Change the password, then require a fresh login with new tokens."""
        self.clear_errors()
        if not self.validate(
            password_errors(self.values()) | required(self.values(), ("current_password",))
        ):
            return
        await self.app.api.request("POST", "auth/password/change/", json=self.values())
        self.app.api.clear_session()
        await self.app.open("auth")
        self.app.notify("Пароль изменён. Войдите заново.")

    def build(self) -> ft.Control:
        """Show the required password rules before submission."""
        return self.scroll(
            title("Изменить пароль"),
            muted("От 8 символов: латинские буквы обоих регистров и хотя бы одна цифра.", 16),
            panel(
                ft.Column(
                    [
                        *self.fields.values(),
                        self.error_text,
                        primary("Изменить пароль", self.app.event(self.submit)),
                    ],
                    spacing=16,
                )
            ),
            ft.TextButton("К профилю", on_click=self.app.event(self.app.open, "profile")),
        )


class SettingsScreen(Screen):
    """Configure the shared backend address for desktop, emulator, or a real phone."""

    nav_index = 2

    def __init__(self, app: object) -> None:
        """Prefill the address currently used by this application session."""
        super().__init__(app)
        self.fields = {
            "base_url": field(
                "Адрес API", value=app.api.base_url, hint_text="http://192.168.1.10:8000/api/v1/"
            )
        }

    async def submit(self) -> None:
        """Check the target server before discarding the current connection or session."""
        self.clear_errors()
        await self.app.change_server(self.fields["base_url"].value)

    def build(self) -> ft.Control:
        """Explain localhost differences without requiring knowledge of database internals."""
        return self.scroll(
            title("Подключение к кинотеатру"),
            panel(
                ft.Column(
                    [
                        self.fields["base_url"],
                        self.error_text,
                        primary("Проверить и подключиться", self.app.event(self.submit)),
                    ],
                    spacing=16,
                )
            ),
            muted("На этом компьютере: http://127.0.0.1:8000/api/v1/", 16),
            muted("В эмуляторе Android: http://10.0.2.2:8000/api/v1/", 16),
            muted(
                "На телефоне: IP-адрес компьютера с сервером. "
                "Оба устройства должны быть в одной сети.",
                16,
            ),
            muted("При смене сервера потребуется войти заново."),
            secondary("Вернуться к афише", self.app.event(self.app.open, "catalog")),
        )
