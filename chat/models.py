import uuid

from django.conf import settings
from django.db import models


class ChatThread(models.Model):
    """A conversation: either a carpool group's standing chat or a single
    trip's "today's run" thread."""

    class ContextType(models.TextChoices):
        CARPOOL_GROUP = "carpool_group"
        TRIP = "trip"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    carpool_group = models.ForeignKey(
        "carpool.CarpoolGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_threads",
    )
    context_type = models.CharField(max_length=15, choices=ContextType.choices)
    trip = models.ForeignKey(
        "trips.Trip",
        on_delete=models.CASCADE,
        null=True,
        blank=True,  # set for a "today's run" thread
        related_name="chat_threads",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_threads"
        constraints = [
            models.UniqueConstraint(
                fields=["carpool_group"],
                condition=models.Q(context_type="carpool_group"),
                name="unique_carpool_group_thread",
            ),
            models.UniqueConstraint(
                fields=["trip"],
                condition=models.Q(context_type="trip"),
                name="unique_trip_thread",
            ),
        ]

    def __str__(self):
        return f"Thread {self.id} ({self.context_type})"


class ChatMessage(models.Model):
    class MessageType(models.TextChoices):
        TEXT = "text"
        IMAGE = "image"
        SYSTEM = "system"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(
        ChatThread, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    content = models.TextField(null=True, blank=True)
    attachment_url = models.URLField(null=True, blank=True)  # Cloudinary
    message_type = models.CharField(
        max_length=10, choices=MessageType.choices, default=MessageType.TEXT
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_messages"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["thread", "created_at"], name="msg_thread_created_idx")
        ]

    def __str__(self):
        return f"Msg {self.id} in {self.thread_id}"


class ChatReadReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        ChatMessage, on_delete=models.CASCADE, related_name="read_receipts"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_read_receipts",
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_read_receipts"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user"], name="unique_message_user_receipt"
            )
        ]

    def __str__(self):
        return f"{self.user} read {self.message_id}"
