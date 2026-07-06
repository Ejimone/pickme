"""Cross-app triggers each land a Notification for the right recipients.

Covers the required pickup cascade (TripStopChild.picked_up_at → PickupEvent →
Notification) plus swap-request, chat-message, and schedule-change triggers.
"""

import datetime

import pytest

from carpool.models import CarpoolAssignment, CarpoolSwapRequest
from chat.models import ChatMessage, ChatThread
from notifications.models import Notification
from schools.models import SchoolCalendarException
from trips.models import Trip, TripStop, TripStopChild

pytestmark = pytest.mark.django_db

DATE = datetime.date(2026, 7, 7)


def _notifs(user, type):
    return Notification.objects.filter(user=user, type=type)


class TestSwapRequestTrigger:
    def test_target_family_is_notified(self, actors, group):
        users, families = actors
        assignment = CarpoolAssignment.objects.create(
            carpool_group=group, date=DATE, driver_family=families["a"]
        )
        CarpoolSwapRequest.objects.create(
            assignment=assignment,
            requested_by=users["a"],
            target_family=families["b"],
        )
        assert _notifs(users["b"], Notification.Type.SWAP_REQUEST).count() == 1
        # Requester's family is not the target → no notification.
        assert _notifs(users["a"], Notification.Type.SWAP_REQUEST).count() == 0


class TestChatMessageTrigger:
    def test_participants_except_sender_notified(self, actors, group):
        users, _ = actors
        thread = ChatThread.objects.get(carpool_group=group)
        ChatMessage.objects.create(
            thread=thread, sender=users["a"], content="running late"
        )
        assert _notifs(users["b"], Notification.Type.CHAT_MESSAGE).count() == 1
        assert _notifs(users["a"], Notification.Type.CHAT_MESSAGE).count() == 0
        # Outsider d is not a participant.
        assert _notifs(users["d"], Notification.Type.CHAT_MESSAGE).count() == 0

    def test_system_message_does_not_notify(self, actors, group):
        users, _ = actors
        thread = ChatThread.objects.get(carpool_group=group)
        ChatMessage.objects.create(
            thread=thread,
            sender=users["a"],
            content="joined",
            message_type=ChatMessage.MessageType.SYSTEM,
        )
        assert _notifs(users["b"], Notification.Type.CHAT_MESSAGE).count() == 0


class TestScheduleChangeTrigger:
    def test_school_families_notified(self, actors, school, children):
        users, _ = actors
        SchoolCalendarException.objects.create(
            school=school, date=DATE, dismissal_time=None, reason="Snow day"
        )
        # a, b, d all have an active child at this school.
        for tag in ["a", "b", "d"]:
            assert (
                _notifs(users[tag], Notification.Type.SCHEDULE_CHANGE).count() == 1
            )


class TestPickupCascade:
    def test_picked_up_notifies_family(self, actors, group, school, children):
        """TripStopChild.picked_up_at → PickupEvent(picked_up) → Notification."""
        users, families = actors
        trip = Trip.objects.create(
            driver=users["a"], carpool_group=group, date=DATE
        )
        stop = TripStop.objects.create(trip=trip, school=school, sequence_order=1)
        entry = TripStopChild.objects.create(trip_stop=stop, child=children["a"])

        # Starting the trip creates the PickupEvent (en_route) via the cascade.
        trip.status = Trip.Status.IN_PROGRESS
        trip.save(update_fields=["status"])

        # The Stage-4 trigger: setting picked_up_at flips the PickupEvent and,
        # in Stage 7, fires the family notification.
        entry.picked_up_at = datetime.datetime(2026, 7, 7, 15, 5, tzinfo=datetime.timezone.utc)
        entry.save(update_fields=["picked_up_at"])

        notifs = _notifs(users["a"], Notification.Type.DRIVER_ARRIVED)
        assert notifs.filter(data__child_id=str(children["a"].id)).count() == 1
        # Family B has no child on this trip → not notified.
        assert _notifs(users["b"], Notification.Type.DRIVER_ARRIVED).count() == 0

    def test_stop_arrived_notifies_stop_families(
        self, actors, group, school, children
    ):
        users, _ = actors
        trip = Trip.objects.create(
            driver=users["a"], carpool_group=group, date=DATE
        )
        stop = TripStop.objects.create(trip=trip, school=school, sequence_order=1)
        TripStopChild.objects.create(trip_stop=stop, child=children["b"])

        stop.status = TripStop.Status.ARRIVED
        stop.save(update_fields=["status"])

        arrived = _notifs(users["b"], Notification.Type.DRIVER_ARRIVED)
        assert arrived.filter(data__stop_id=str(stop.id)).count() == 1
        # Re-saving the arrived stop does not duplicate (dedupe_key).
        stop.save(update_fields=["status"])
        assert arrived.filter(data__stop_id=str(stop.id)).count() == 1
