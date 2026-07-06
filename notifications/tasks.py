"""Notification Celery tasks.

`poll_upcoming_dismissals` is the poller pattern from SYSTEMS-DEEP-DIVE.md §1:
one frequent beat task fans out per-child `send_dismissal_reminder` jobs, so we
never need a per-school beat schedule. Reminders and pushes are both idempotent
(dedupe_key / delivered_at markers) so re-dispatch never double-sends.
"""

import datetime
from zoneinfo import ZoneInfo

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from notifications.models import Notification


@shared_task
def poll_upcoming_dismissals():
    """Every ~5 min: find children whose effective pickup lands inside the
    reminder window [now, now + offset) and dispatch one reminder per child.

    Recipients differ per family, so the fan-out is per child (not per school),
    and the actual send/dedupe happens in `send_dismissal_reminder`.
    """
    from families.models import Child
    from schools.services import resolve_effective_pickup_time

    now = timezone.now()
    window_end = now + datetime.timedelta(
        minutes=settings.DISMISSAL_REMINDER_OFFSET_MINUTES
    )
    dispatched = 0
    children = (
        Child.objects.filter(is_active=True, school__isnull=False)
        .select_related("school", "family")
    )
    for child in children:
        local_date = now.astimezone(ZoneInfo(child.school.timezone)).date()
        pickup_at = resolve_effective_pickup_time(child, local_date)
        if pickup_at is None:
            continue
        if now <= pickup_at < window_end:
            send_dismissal_reminder.delay(str(child.id), local_date.isoformat())
            dispatched += 1
    return dispatched


@shared_task
def send_dismissal_reminder(child_id, date):
    """Notify every member of a child's family that pickup is coming up.

    Idempotent via a per-(user, child, date) dedupe key, so re-dispatch within
    the same window is a no-op.
    """
    from families.models import Child
    from notifications.services import notify_users

    if isinstance(date, str):
        date = datetime.date.fromisoformat(date)

    child = (
        Child.objects.filter(id=child_id)
        .select_related("school", "family")
        .first()
    )
    if child is None or child.school is None:
        return 0

    recipients = [
        member.user for member in child.family.members.select_related("user")
    ]
    when = ""
    from schools.services import resolve_effective_pickup_time

    pickup_at = resolve_effective_pickup_time(child, date)
    if pickup_at is not None:
        local = pickup_at.astimezone(ZoneInfo(child.school.timezone))
        when = f" at {local:%-I:%M %p}"

    created = notify_users(
        recipients,
        type=Notification.Type.PICKUP_REMINDER,
        title="Pickup reminder",
        body=f"{child.full_name} is dismissed from {child.school.name}{when}.",
        data={"child_id": str(child.id), "date": date.isoformat()},
        dedupe_key=lambda user: (
            f"pickup_reminder:{user.id}:{child.id}:{date.isoformat()}"
        ),
    )
    return len(created)


@shared_task
def send_push_notification(notification_id):
    """Fan a single notification out to the recipient's Expo device tokens.

    Sets `delivered_at` before returning so a retry never double-sends
    (SYSTEMS-DEEP-DIVE.md §1). Honors the user's per-type push preference.
    """
    from notifications.services import get_push_client, push_wanted

    notification = (
        Notification.objects.filter(id=notification_id)
        .select_related("user")
        .first()
    )
    if notification is None or notification.delivered_at is not None:
        return 0  # gone or already delivered

    if not push_wanted(notification.user, notification.type):
        notification.delivered_at = timezone.now()  # respected, don't retry
        notification.save(update_fields=["delivered_at"])
        return 0

    tokens = list(
        notification.user.device_tokens.values_list("token", flat=True)
    )
    if tokens:
        messages = [
            {
                "to": token,
                "title": notification.title,
                "body": notification.body,
                "data": notification.data or {},
            }
            for token in tokens
        ]
        get_push_client().send(messages)

    notification.delivered_at = timezone.now()
    notification.save(update_fields=["delivered_at"])
    return len(tokens)
