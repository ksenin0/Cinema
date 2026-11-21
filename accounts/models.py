"""Shared identity model for web personnel and future client applications."""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class User(AbstractUser):
    """Django identity with case-insensitive login/email uniqueness and a business role."""

    class Role(models.TextChoices):
        CLIENT = "client", "Клиент"
        CASHIER = "cashier", "Кассир"
        ADMIN = "admin", "Администратор"

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=25, blank=True)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.CLIENT)
    created_at = models.DateTimeField(auto_now_add=True)
    REQUIRED_FIELDS = ["email"]

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="user_email_case_insensitive"),
            models.UniqueConstraint(Lower("username"), name="user_username_case_insensitive"),
        ]

    def save(self, *args: object, **kwargs: object) -> None:
        """Normalize email and align Django Admin access with personnel roles."""
        self.email = self.email.strip().lower()
        self.is_staff = self.is_superuser or self.role in {self.Role.CASHIER, self.Role.ADMIN}
        super().save(*args, **kwargs)
