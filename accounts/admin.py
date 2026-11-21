"""System-administrator-only personnel account management."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Only superusers may administer identities and personnel roles."""

    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Кинотеатр", {"fields": ("phone", "role", "created_at")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Кинотеатр", {"fields": ("email", "phone", "role")}),
    )
    readonly_fields = ["created_at"]
    list_display = ["username", "email", "role", "is_active", "is_superuser"]

    def has_module_permission(self, request: object) -> bool:
        """Hide account management from ordinary administrators and cashiers."""
        return request.user.is_superuser

    def has_view_permission(self, request: object, obj: object = None) -> bool:
        """Restrict identity viewing to system administrators."""
        return request.user.is_superuser

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        """Restrict identity editing to system administrators."""
        return request.user.is_superuser

    def has_add_permission(self, request: object) -> bool:
        """Restrict personnel creation to system administrators."""
        return request.user.is_superuser

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        """Restrict physical identity deletion to system administrators."""
        return request.user.is_superuser
