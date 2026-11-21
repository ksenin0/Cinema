"""Explicit account input contracts prevent role and privilege escalation."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from accounts.models import User
from accounts.services import register_client


class UserSerializer(serializers.ModelSerializer):
    """Expose profile fields; role and identity metadata are always read-only."""

    email = serializers.EmailField(
        validators=[UniqueValidator(queryset=User.objects.all(), lookup="iexact")]
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "created_at",
        ]
        read_only_fields = ["id", "username", "role", "created_at"]


class RegisterSerializer(serializers.ModelSerializer):
    """Validate registration, confirmation, and case-insensitive identity uniqueness."""

    username = serializers.CharField(
        max_length=150,
        validators=[
            UniqueValidator(queryset=User.objects.all(), lookup="iexact"),
            User._meta.get_field("username").validators[0],
        ],
    )
    email = serializers.EmailField(
        validators=[UniqueValidator(queryset=User.objects.all(), lookup="iexact")]
    )
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=25)

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "password",
            "password_confirm",
            "first_name",
            "last_name",
            "phone",
        ]

    def validate(self, attrs: dict) -> dict:
        """Reject mismatched/weak passwords using a candidate user's profile."""
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Пароли не совпадают."})
        candidate = User(**{key: value for key, value in attrs.items() if key != "password"})
        validate_password(attrs["password"], candidate)
        return attrs

    def create(self, validated_data: dict) -> User:
        """Delegate hashing and registration notification to the account service."""
        return register_client(validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    """Current password plus the new password and its confirmation."""

    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)
    new_password_confirm = serializers.CharField(trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        """Check the current secret and validate the replacement; raise ValidationError."""
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Неверный текущий пароль."})
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "Пароли не совпадают."})
        validate_password(attrs["new_password"], user)
        return attrs


class ResetRequestSerializer(serializers.Serializer):
    """Password reset initiation input."""

    email = serializers.EmailField()


class ResetConfirmSerializer(serializers.Serializer):
    """One-time reset token and password replacement input."""

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(trim_whitespace=False)
    new_password_confirm = serializers.CharField(trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        """Resolve and validate a one-time token; return the user with validated input."""
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = get_user_model().objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, UnicodeDecodeError, User.DoesNotExist) as exc:
            raise serializers.ValidationError("Недействительный код восстановления.") from exc
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError("Токен недействителен или уже использован.")
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "Пароли не совпадают."})
        validate_password(attrs["new_password"], user)
        return {**attrs, "user": user}


class WebLoginSerializer(serializers.Serializer):
    """Personnel login input."""

    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


class DeactivateSerializer(serializers.Serializer):
    """Require password confirmation before anonymizing the account."""

    current_password = serializers.CharField(trim_whitespace=False)

    def validate_current_password(self, value: str) -> str:
        """Reject deactivation when the current password is incorrect."""
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Неверный текущий пароль.")
        return value
