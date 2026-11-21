"""Shared screen and form behavior."""

from typing import TYPE_CHECKING

import flet as ft

from cinema_client.api import ApiError
from cinema_client.theme import DANGER

if TYPE_CHECKING:
    from cinema_client.app import CinemaApp


class Screen:
    """A client screen owns its controls and optional asynchronous data load."""

    nav_index = 0

    def __init__(self, app: "CinemaApp") -> None:
        """Keep the controller dependency; no HTTP calls are made during construction."""
        self.app = app
        self.fields: dict[str, ft.TextField] = {}
        self.error_text = ft.Text(color=DANGER, selectable=True, visible=False)

    async def load(self) -> None:
        """Load any remote data before the screen is first rendered."""

    def build(self) -> ft.Control:
        """Return this screen's root control; concrete screens implement this method."""
        raise NotImplementedError

    def scroll(self, *controls: ft.Control) -> ft.ListView:
        """Wrap screen content in one vertical scroll area, with comfortable spacing."""
        return ft.ListView(controls=list(controls), expand=True, spacing=20, padding=0)

    def values(self) -> dict[str, str]:
        """Read form values without stripping significant password whitespace."""
        return {
            name: control.value if control.password else control.value.strip()
            for name, control in self.fields.items()
        }

    def clear_errors(self) -> None:
        """Clear prior validation feedback before a new submission."""
        self.error_text.visible = False
        for control in self.fields.values():
            control.error_text = None

    def validate(self, errors: dict[str, list[str]]) -> bool:
        """Display local validation errors and return whether the form may be submitted."""
        if errors:
            self.display_error(ApiError("Проверьте заполненные поля.", 400, errors))
        return not errors

    def display_error(self, error: ApiError) -> bool:
        """Attach server validation details to fields; return whether this is a form screen."""
        if not self.fields:
            return False
        self.error_text.value = error.message
        self.error_text.visible = True
        for name, detail in error.errors.items():
            text = (
                "; ".join(str(item) for item in detail) if isinstance(detail, list) else str(detail)
            )
            if name in self.fields:
                self.fields[name].error_text = text
            elif name not in {"status", "message", "errors"}:
                self.error_text.value += f"\n{text}"
        return True
