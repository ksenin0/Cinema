"""Role policies used by REST endpoints."""

from rest_framework.permissions import SAFE_METHODS, BasePermission


def has_role(user: object, *roles: str) -> bool:
    """Return whether an active authenticated user has one of roles or is superuser."""
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_superuser or user.role in roles)
    )


class CatalogPermission(BasePermission):
    """Allow public reads and restrict catalog mutations to administrators."""

    def has_permission(self, request: object, view: object) -> bool:
        """Evaluate request method and the authenticated user's role."""
        return request.method in SAFE_METHODS or has_role(request.user, "admin")


class CashierPermission(BasePermission):
    """Permit cashiers and administrators to sell and validate tickets."""

    def has_permission(self, request: object, view: object) -> bool:
        """Return True only for personnel allowed to handle sales."""
        return has_role(request.user, "cashier", "admin")


class ReportPermission(BasePermission):
    """Permit administrators to access financial reports."""

    def has_permission(self, request: object, view: object) -> bool:
        """Return whether the request is made by an administrator."""
        return has_role(request.user, "admin")
