"""Keep Django groups aligned with application roles."""

from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from accounts.models import User

ROLE_GROUPS = {"client": "Клиенты", "cashier": "Кассиры", "admin": "Администраторы"}


@receiver(post_migrate)
def configure_role_groups(sender: object, **kwargs: object) -> None:
    """Create groups and grant narrow model permissions after migrations."""
    # Run after catalog/bookings content types and permissions have been created.
    if sender.name != "notifications":
        return
    for role, name in ROLE_GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        permissions = Permission.objects.none()
        if role == "admin":
            permissions = Permission.objects.filter(content_type__app_label="catalog")
        if role in {"cashier", "admin"}:
            permissions = permissions | Permission.objects.filter(
                content_type__app_label__in=["catalog", "bookings"], codename__startswith="view_"
            )
        group.permissions.set(permissions)


@receiver(post_save, sender=User)
def synchronize_role_group(sender: object, instance: User, **kwargs: object) -> None:
    """Replace only managed role groups, retaining unrelated custom memberships."""
    if kwargs.get("raw"):
        return
    instance.groups.remove(*Group.objects.filter(name__in=ROLE_GROUPS.values()))
    group, _ = Group.objects.get_or_create(name=ROLE_GROUPS[instance.role])
    instance.groups.add(group)
