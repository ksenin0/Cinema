"""Public API discovery without weakening permissions on individual resources."""

from django.urls import reverse
from rest_framework.permissions import AllowAny
from rest_framework.routers import APIRootView, DefaultRouter


class PublicApiRootView(APIRootView):
    """Let visitors open the browsable API index before signing in."""

    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        """Expose the staff workspace alongside API resources."""
        response = super().get(request, *args, **kwargs)
        response.data["cashier"] = request.build_absolute_uri(reverse("cashier:index"))
        return response


class PublicRootRouter(DefaultRouter):
    """Keep resource policies intact while making only API discovery public."""

    APIRootView = PublicApiRootView
