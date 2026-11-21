"""Session login restricted to active cinema personnel."""

from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from common.permissions import has_role


class CashierAuthenticationForm(AuthenticationForm):
    """Reuse Django authentication and apply the shared cashier role policy."""

    def confirm_login_allowed(self, user):
        """Keep customer accounts outside the personnel workspace."""
        super().confirm_login_allowed(user)
        if not has_role(user, "cashier", "admin"):
            raise ValidationError("Для входа нужна учётная запись кассира или администратора.")
