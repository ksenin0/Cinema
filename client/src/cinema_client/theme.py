"""Semantic visual tokens and small reusable Material components."""

import flet as ft

BACKGROUND = "#10121A"
SURFACE = "#1A1D29"
SURFACE_HIGH = "#242938"
BORDER = "#3F465C"
TEXT = "#F4F5FA"
MUTED = "#B3B9CE"
ACCENT = "#F4C66A"
ON_ACCENT = "#211A0C"
SUCCESS = "#8BDEB2"
DANGER = "#FFAAA7"
VIP = "#CEB4FF"


def title(value: str, size: int = 28) -> ft.Text:
    """Create a readable screen or section heading."""
    return ft.Text(value, size=size, weight=ft.FontWeight.W_700, color=TEXT)


def muted(value: str, size: int = 14) -> ft.Text:
    """Create secondary text with sufficient contrast on dark surfaces."""
    return ft.Text(value, size=size, color=MUTED)


def badge(value: str, color: str = ACCENT) -> ft.Container:
    """Build a compact text status that remains meaningful without color."""
    return ft.Container(
        ft.Text(value, color=color, size=12, weight=ft.FontWeight.W_600),
        bgcolor=SURFACE_HIGH,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        border_radius=8,
    )


def panel(content: ft.Control, padding: int = 20) -> ft.Container:
    """Group related information on a bordered dark surface."""
    return ft.Container(
        content, bgcolor=SURFACE, padding=padding, border=ft.Border.all(1, BORDER), border_radius=16
    )


def primary(label: str, handler: object, icon: object = None, **kwargs: object) -> ft.Button:
    """Create a consistent forty-eight-pixel primary action."""
    return ft.Button(
        label,
        icon=icon,
        on_click=handler,
        height=48,
        bgcolor=ACCENT,
        color=ON_ACCENT,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        **kwargs,
    )


def secondary(
    label: str, handler: object, icon: object = None, **kwargs: object
) -> ft.OutlinedButton:
    """Create a secondary action with an accessible tap target."""
    return ft.OutlinedButton(
        label,
        icon=icon,
        on_click=handler,
        height=48,
        style=ft.ButtonStyle(
            color=TEXT, side=ft.BorderSide(1, BORDER), shape=ft.RoundedRectangleBorder(radius=10)
        ),
        **kwargs,
    )


def field(label: str, *, password: bool = False, value: str = "", **kwargs: object) -> ft.TextField:
    """Build a labelled native input with password-manager and paste support."""
    return ft.TextField(
        label=label,
        value=value,
        password=password,
        can_reveal_password=password,
        autocorrect=not password,
        enable_suggestions=not password,
        smart_dashes_type=not password,
        smart_quotes_type=not password,
        color=TEXT,
        border_color=BORDER,
        focused_border_color=ACCENT,
        filled=True,
        fill_color=SURFACE,
        text_size=16,
        border_radius=10,
        **kwargs,
    )


def empty_state(
    message: str, explanation: str = "", action: ft.Control | None = None
) -> ft.Container:
    """Show a clear empty/error state with an optional recovery action."""
    controls = [ft.Icon(ft.Icons.LOCAL_MOVIES_OUTLINED, size=42, color=ACCENT), title(message, 21)]
    if explanation:
        controls.append(muted(explanation, 16))
    if action:
        controls.append(action)
    return panel(ft.Column(controls, spacing=16), padding=28)
