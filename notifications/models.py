"""Transactional email outbox; network delivery occurs outside booking transactions."""

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Retryable pending email, optionally referring to an order for ticket attachments."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    order = models.ForeignKey("bookings.Order", null=True, blank=True, on_delete=models.CASCADE)
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
