"""Catalog file validation."""

from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


def validate_poster(file: object) -> None:
    """Accept verified JPEG/PNG files up to 5 MiB; raise ValidationError otherwise."""
    if file.size > 5 * 1024 * 1024:
        raise ValidationError("Постер должен быть не больше 5 МБ.")
    try:
        image = Image.open(file)
        if image.format not in {"JPEG", "PNG"}:
            raise ValidationError("Допустимы только JPG, JPEG и PNG.")
        image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("Повреждённое или недопустимое изображение.") from exc
    finally:
        file.seek(0)
