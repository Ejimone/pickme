import uuid

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """An in-app / push notification for one user (DATABASE-SCHEMA.md §22).

    Two fields go beyond the schema table, both documented in DECISIONS.md:
      - `delivered_at`: set by `send_push_notification` before hitting Expo so
        retries never double-send (SYSTEMS-DEEP-DIVE.md §1).
      - `dedupe_key`: nullable, unique-when-set idempotency marker so a beat
        re-dispatch (dismissal reminders) or a re-saved trip stop never
        creates a duplicate row.
    """

    class Type(models.TextChoices):
        PICKUP_REMINDER = "pickup_reminder"
        DRIVER_ARRIVED = "driver_arrived"
        SWAP_REQUEST = "swap_request"
        CHAT_MESSAGE = "chat_message"
        SCHEDULE_CHANGE = "schedule_change"
        SOS = "sos"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(null=True, blank=True)  # deep-link payload
    is_read = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dedupe_key"],
                condition=models.Q(dedupe_key__isnull=False),
                name="unique_notification_dedupe_key",
            )
        ]

    def __str__(self):
        return f"{self.type} → {self.user} ({'read' if self.is_read else 'unread'})"


class NotificationPreference(models.Model):
    """Per-user channel toggles for one notification type (§23).

    A missing row means "all channels on" — see `notifications.services`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_type = models.CharField(
        max_length=20, choices=Notification.Type.choices
    )
    push_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    email_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_preferences"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "notification_type"],
                name="unique_user_notification_type",
            )
        ]

    def __str__(self):
        return f"{self.user} / {self.notification_type}"


class DeviceToken(models.Model):
    """A registered Expo push token for one of a user's devices (§24)."""

    class Platform(models.TextChoices):
        IOS = "ios"
        ANDROID = "android"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_tokens",
    )
    token = models.CharField(max_length=255, unique=True)  # Expo push token
    platform = models.CharField(max_length=10, choices=Platform.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "device_tokens"

    def __str__(self):
        return f"{self.user} ({self.platform})"
