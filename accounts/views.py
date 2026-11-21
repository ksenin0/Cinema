"""HTTP account endpoints for browser sessions and future JWT clients."""

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import generics, permissions, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.serializers import (
    ChangePasswordSerializer,
    DeactivateSerializer,
    RegisterSerializer,
    ResetConfirmSerializer,
    ResetRequestSerializer,
    UserSerializer,
    WebLoginSerializer,
)
from accounts.services import deactivate_user, request_password_reset
from common.permissions import has_role


class PublicAuthView(APIView):
    """Public authentication endpoints with stricter per-IP throttling."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class LoginTokenView(TokenObtainPairView):
    """Obtain JWT access/refresh tokens with authentication throttling."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RefreshTokenView(TokenRefreshView):
    """Rotate and blacklist refresh tokens under the same throttling policy."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RegisterView(generics.CreateAPIView):
    """Create a client account; personnel accounts are managed by a superuser."""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class ProfileView(generics.RetrieveUpdateAPIView):
    """View/update the current user's safe profile fields and deactivate an account."""

    serializer_class = UserSerializer

    def get_object(self) -> object:
        """Return only the current authenticated user."""
        return self.request.user

    def delete(self, request: Request) -> Response:
        """Anonymize the authenticated account after validating its current password."""
        serializer = DeactivateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        deactivate_user(request.user)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordChangeView(APIView):
    """Change the current user's password and invalidate password-bound JWTs."""

    def post(self, request: Request) -> Response:
        """Validate both passwords and persist a Django password hash."""
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        logout(request)
        return Response({"message": "Пароль изменён. Войдите заново."})


class PasswordResetRequestView(PublicAuthView):
    """Queue recovery instructions without disclosing whether an address exists."""

    def post(self, request: Request) -> Response:
        """Accept an email and always return the same successful response."""
        serializer = ResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_password_reset(serializer.validated_data["email"])
        return Response({"message": "Если учётная запись существует, письмо будет отправлено."})


class PasswordResetConfirmView(PublicAuthView):
    """Consume a one-time reset token atomically."""

    @transaction.atomic
    def post(self, request: Request) -> Response:
        """Validate the reset token and change the password in a single transaction."""
        serializer = ResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save()
        return Response({"message": "Пароль восстановлен."})


class CsrfView(APIView):
    """Provide a CSRF cookie/token before browser session authentication."""

    permission_classes = [permissions.AllowAny]

    def get(self, request: Request) -> Response:
        """Return the token to send as X-CSRFToken for browser mutations."""
        return Response({"csrf_token": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class WebLoginView(PublicAuthView):
    """Authenticate personnel with Django sessions and mandatory CSRF validation."""

    def post(self, request: Request) -> Response:
        """Create a staff session or return a generic authentication failure."""
        serializer = WebLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request=request, **serializer.validated_data)
        if not has_role(user, "cashier", "admin"):
            raise AuthenticationFailed("Неверные данные входа сотрудника.")
        login(request, user)
        return Response(UserSerializer(user).data)


class WebLogoutView(APIView):
    """End an authenticated Django session."""

    def post(self, request: Request) -> Response:
        """Flush the current browser session and return HTTP 204."""
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
