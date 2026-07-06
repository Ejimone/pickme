"""Notification creation, in-app WebSocket fan-out, and the Expo push client.

`create_notification` is the single write path — REST endpoints, Celery tasks
and cross-app trigger signals all go through it, so every notification row
gets the same `notification.new` WebSocket broadcast and (via the post_save
signal) the same push-fan-out dispatch.

The Expo client is selected via `PUSH_BACKEND` ("fake" | "expo"), mirroring the
Maps client in `trips.services`, so tests and local dev never hit exp.host.
"""

import requests
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

from notifications.models import Notification, NotificationPreference


# --- Expo push service (selectable backend) ---------------------------------


class FakeExpoPushService:
    """Records messages instead of sending them; for tests/local dev."""

    def __init__(self):
        self.sent = []

    def send(self, messages):
        self.sent.extend(messages)
        return {"data": [{"status": "ok"} for _ in messages]}


class ExpoPushService:
    def send(self, messages):
        if not messages:
            return {"data": []}
        response = requests.post(
            settings.EXPO_PUSH_URL,
            json=messages,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()


def get_push_client():
    if settings.PUSH_BACKEND == "expo":
        return ExpoPushService()
    return FakeExpoPushService()


# --- In-app WebSocket fan-out -----------------------------------------------


def serialize_notification(notification):
    return {
        "id": str(notification.id),
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "data": notification.data,
        "is_read": notification.is_read,
        "created_at": notification.created_at.isoformat(),
    }


def broadcast_notification(notification):
    """group_send `notification.new` to the recipient's personal channel group
    (`user_{user_id}`), consumed by `NotificationConsumer`."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{notification.user_id}",
        {
            "type": "notification.new",
            "notification": serialize_notification(notification),
        },
    )


# --- Creation (the single write path) ---------------------------------------


def create_notification(*, user, type, title, body, data=None, dedupe_key=None):
    """Create one notification, or return the existing one when `dedupe_key`
    is set and already present (idempotent). Returns (notification, created).

    The post_save signal handles the WebSocket broadcast and push dispatch, so
    callers never need to fan out themselves.
    """
    if dedupe_key:
        return Notification.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "user": user,
                "type": type,
                "title": title,
                "body": body,
                "data": data,
            },
        )
    notification = Notification.objects.create(
        user=user, type=type, title=title, body=body, data=data
    )
    return notification, True


def notify_users(users, *, type, title, body, data=None, dedupe_key=None):
    """Create a notification for each user. `dedupe_key`, when given, is a
    callable taking a user and returning that user's key (keys must differ per
    user so one recipient's marker never suppresses another's)."""
    created = []
    for user in users:
        key = dedupe_key(user) if callable(dedupe_key) else dedupe_key
        notification, was_created = create_notification(
            user=user, type=type, title=title, body=body, data=data, dedupe_key=key
        )
        if was_created:
            created.append(notification)
    return created


def push_wanted(user, notification_type):
    """Whether this user wants push for this type. A missing preference row
    means "on" (default-enabled, per the schema field defaults)."""
    pref = NotificationPreference.objects.filter(
        user=user, notification_type=notification_type
    ).first()
    return pref.push_enabled if pref is not None else True
