"""Notification fan-out and the cross-app triggers that create notifications.

Two layers:

1. `on_notification_saved` — the single fan-out point. Every newly created
   `Notification` is broadcast over WebSocket (`notification.new`) and queued
   for Expo push. Nothing else in the codebase pushes; producers just create a
   `Notification` (via `notifications.services.create_notification`).

2. Trigger receivers on other apps' models — swap requested, chat message,
   schedule change, driver arrived, child picked up — each translating a domain
   event into `create_notification` calls. They stay thin per working rule #7:
   resolve recipients, then delegate.
"""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from carpool.models import CarpoolSwapRequest
from chat.models import ChatMessage
from notifications import recipients
from notifications.models import Notification
from notifications.services import broadcast_notification, notify_users
from schools.models import SchoolCalendarException
from trips.models import PickupEvent, TripStop


# --- 1. Fan-out --------------------------------------------------------------


@receiver(post_save, sender=Notification)
def on_notification_saved(sender, instance, created, **kwargs):
    if not created:
        return
    broadcast_notification(instance)  # in-app, instant
    # Background push: dispatch after commit so the worker sees the row.
    from notifications.tasks import send_push_notification

    transaction.on_commit(
        lambda: send_push_notification.delay(str(instance.id))
    )


# --- 2. Triggers -------------------------------------------------------------


@receiver(post_save, sender=CarpoolSwapRequest)
def on_swap_requested(sender, instance, created, **kwargs):
    if not created:
        return
    assignment = instance.assignment
    notify_users(
        recipients.family_recipients(instance.target_family),
        type=Notification.Type.SWAP_REQUEST,
        title="Carpool swap request",
        body=(
            f"{instance.requested_by.full_name or instance.requested_by.email} "
            f"asked your family to drive on {assignment.date:%b %-d}."
        ),
        data={
            "swap_request_id": str(instance.id),
            "assignment_id": str(assignment.id),
            "carpool_group_id": str(assignment.carpool_group_id),
            "date": assignment.date.isoformat(),
        },
    )


@receiver(post_save, sender=ChatMessage)
def on_chat_message(sender, instance, created, **kwargs):
    if not created or instance.message_type == ChatMessage.MessageType.SYSTEM:
        return
    audience = [
        user
        for user in recipients.thread_recipients(instance.thread)
        if user.id != instance.sender_id
    ]
    sender_name = instance.sender.full_name or instance.sender.email
    preview = instance.content or "Sent an attachment"
    notify_users(
        audience,
        type=Notification.Type.CHAT_MESSAGE,
        title=f"New message from {sender_name}",
        body=preview[:140],
        data={
            "thread_id": str(instance.thread_id),
            "message_id": str(instance.id),
        },
    )


@receiver(post_save, sender=SchoolCalendarException)
def on_schedule_change(sender, instance, created, **kwargs):
    verb = "added" if created else "updated"
    if instance.dismissal_time is None:
        detail = "no school"
    else:
        detail = f"dismissal at {instance.dismissal_time:%-I:%M %p}"
    notify_users(
        recipients.school_recipients(instance.school),
        type=Notification.Type.SCHEDULE_CHANGE,
        title="Schedule change",
        body=(
            f"{instance.school.name} on {instance.date:%b %-d}: "
            f"{instance.reason} ({detail})."
        ),
        data={"school_id": str(instance.school_id), "date": instance.date.isoformat()},
    )


@receiver(post_save, sender=TripStop)
def on_driver_arrived(sender, instance, created, **kwargs):
    if created or instance.status != TripStop.Status.ARRIVED:
        return
    where = instance.school.name if instance.school_id else "the stop"
    notify_users(
        recipients.trip_stop_recipients(instance),
        type=Notification.Type.DRIVER_ARRIVED,
        title="Driver has arrived",
        body=f"Your driver has arrived at {where}.",
        data={"trip_id": str(instance.trip_id), "stop_id": str(instance.id)},
        # One arrival notification per user per stop.
        dedupe_key=lambda user: f"driver_arrived:{user.id}:{instance.id}",
    )


@receiver(post_save, sender=PickupEvent)
def on_child_picked_up(sender, instance, created, **kwargs):
    """The Stage-4 cascade tail (SYSTEMS-DEEP-DIVE.md §4): a PickupEvent moving
    to `picked_up` notifies every member of that child's family. The schema's
    notification-type enum has no `picked_up`, so this reuses `driver_arrived`
    (documented in DECISIONS.md)."""
    if created or instance.status != PickupEvent.Status.PICKED_UP:
        return
    child = instance.child
    notify_users(
        recipients.family_recipients(child.family),
        type=Notification.Type.DRIVER_ARRIVED,
        title="Picked up",
        body=f"{child.full_name} has been picked up.",
        data={
            "child_id": str(child.id),
            "pickup_event_id": str(instance.id),
            "date": instance.date.isoformat(),
        },
        dedupe_key=lambda user: (
            f"picked_up:{user.id}:{child.id}:{instance.date.isoformat()}"
        ),
    )
