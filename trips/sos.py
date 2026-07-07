"""SOS fan-out — the safety path, kept deliberately separate from the normal
notification queue.

`fan_out_sos` delivers an alert to every guardian tied to the trip through two
channels at once:
  1. Push: a `type=sos` Notification per guardian, pushed to Expo *immediately*
     (synchronously in-request) rather than via the deferred `on_commit` queue,
     so an emergency never waits behind other work. The generic post_save
     signal still queues a push, but `delivered_at` makes that a no-op.
  2. WebSocket: an `sos_alert` event to the trip's live-tracking group
     (`trip_{trip_id}`), so anyone with the map open sees it instantly, plus
     the per-guardian `notification.new` the Notification signal already emits.
"""

from notifications.models import Notification
from notifications.recipients import trip_recipients
from notifications.services import create_notification
from notifications.tasks import send_push_notification
from trips.services import broadcast_to_trip


def serialize_alert(alert):
    return {
        "id": str(alert.id),
        "trip_id": str(alert.trip_id) if alert.trip_id else None,
        "raised_by": str(alert.raised_by_id),
        "lat": str(alert.lat) if alert.lat is not None else None,
        "lng": str(alert.lng) if alert.lng is not None else None,
        "message": alert.message,
        "status": alert.status,
        "created_at": alert.created_at.isoformat(),
    }


def sos_recipients(alert):
    """Guardians to alert, excluding the person who raised it (they know)."""
    if alert.trip_id is None:
        return []
    return [
        user
        for user in trip_recipients(alert.trip)
        if user.id != alert.raised_by_id
    ]


def fan_out_sos(alert):
    """Create + immediately deliver the alert. Returns the notifications made."""
    who = alert.raised_by.full_name or alert.raised_by.email
    body = alert.message or f"{who} raised an SOS alert."
    data = {
        "sos_alert_id": str(alert.id),
        "trip_id": str(alert.trip_id) if alert.trip_id else None,
        "lat": str(alert.lat) if alert.lat is not None else None,
        "lng": str(alert.lng) if alert.lng is not None else None,
    }

    notifications = []
    for user in sos_recipients(alert):
        notification, _ = create_notification(
            user=user,
            type=Notification.Type.SOS,
            title="🚨 SOS alert",
            body=body,
            data=data,
        )
        notifications.append(notification)

    # Immediate push — bypass the deferred queue.
    for notification in notifications:
        send_push_notification(str(notification.id))

    # Live-tracking watchers on the trip channel.
    if alert.trip_id:
        broadcast_to_trip(
            alert.trip_id,
            {"type": "sos_alert", "sos": serialize_alert(alert)},
        )

    return notifications
