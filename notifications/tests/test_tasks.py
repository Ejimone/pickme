"""Celery task behavior: push fan-out idempotency + preference gating, the
dismissal-reminder dedupe, and the poller dispatch window.
"""

import datetime

import pytest
from django.utils import timezone

from carpool.tests.conftest import make_user_with_family
from notifications import services
from notifications.models import (
    DeviceToken,
    Notification,
    NotificationPreference,
)
from notifications.services import create_notification
from notifications.tasks import (
    poll_upcoming_dismissals,
    send_dismissal_reminder,
    send_push_notification,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def capturing_expo(monkeypatch):
    client = services.FakeExpoPushService()
    monkeypatch.setattr(services, "get_push_client", lambda: client)
    return client


class TestSendPush:
    def test_fans_out_to_tokens_and_marks_delivered(
        self, actors, capturing_expo
    ):
        users, _ = actors
        DeviceToken.objects.create(
            user=users["a"], token="ExponentPushToken[1]", platform="ios"
        )
        DeviceToken.objects.create(
            user=users["a"], token="ExponentPushToken[2]", platform="android"
        )
        notification, _ = create_notification(
            user=users["a"],
            type=Notification.Type.CHAT_MESSAGE,
            title="Hi",
            body="there",
        )

        sent = send_push_notification(str(notification.id))
        assert sent == 2
        assert {m["to"] for m in capturing_expo.sent} == {
            "ExponentPushToken[1]",
            "ExponentPushToken[2]",
        }
        notification.refresh_from_db()
        assert notification.delivered_at is not None

    def test_idempotent_second_call_no_resend(self, actors, capturing_expo):
        users, _ = actors
        DeviceToken.objects.create(
            user=users["a"], token="ExponentPushToken[1]", platform="ios"
        )
        notification, _ = create_notification(
            user=users["a"],
            type=Notification.Type.CHAT_MESSAGE,
            title="Hi",
            body="there",
        )
        assert send_push_notification(str(notification.id)) == 1
        # already delivered → skipped, nothing new pushed
        assert send_push_notification(str(notification.id)) == 0
        assert len(capturing_expo.sent) == 1

    def test_push_disabled_preference_skips_send(self, actors, capturing_expo):
        users, _ = actors
        DeviceToken.objects.create(
            user=users["a"], token="ExponentPushToken[1]", platform="ios"
        )
        NotificationPreference.objects.create(
            user=users["a"],
            notification_type=Notification.Type.CHAT_MESSAGE,
            push_enabled=False,
        )
        notification, _ = create_notification(
            user=users["a"],
            type=Notification.Type.CHAT_MESSAGE,
            title="Hi",
            body="there",
        )
        assert send_push_notification(str(notification.id)) == 0
        assert capturing_expo.sent == []
        notification.refresh_from_db()
        assert notification.delivered_at is not None  # marked, won't retry


class TestDismissalReminder:
    def test_notifies_every_family_member_once(self, actors, children):
        users, families = actors
        # Add a second member to family A so we assert per-member fan-out.
        from families.models import FamilyMember

        second, _ = make_user_with_family("a2")
        FamilyMember.objects.create(family=families["a"], user=second)

        child = children["a"]
        count = send_dismissal_reminder(str(child.id), "2026-07-07")
        assert count == 2  # owner + second member

        # Re-dispatch within the same window is a no-op (dedupe_key).
        assert send_dismissal_reminder(str(child.id), "2026-07-07") == 0
        assert (
            Notification.objects.filter(
                type=Notification.Type.PICKUP_REMINDER
            ).count()
            == 2
        )


class TestPoller:
    def test_dispatches_for_child_in_window(
        self, actors, children, monkeypatch
    ):
        dispatched = []
        monkeypatch.setattr(
            send_dismissal_reminder,
            "delay",
            lambda child_id, date: dispatched.append((child_id, date)),
        )
        # Force the child's effective pickup to land inside the window.
        soon = timezone.now() + datetime.timedelta(minutes=10)
        monkeypatch.setattr(
            "schools.services.resolve_effective_pickup_time",
            lambda child, date: soon,
        )

        n = poll_upcoming_dismissals()
        assert n == 3  # one per active child at a school (a, b, d)
        assert len(dispatched) == 3

    def test_skips_child_outside_window(self, actors, children, monkeypatch):
        dispatched = []
        monkeypatch.setattr(
            send_dismissal_reminder,
            "delay",
            lambda child_id, date: dispatched.append((child_id, date)),
        )
        later = timezone.now() + datetime.timedelta(hours=5)
        monkeypatch.setattr(
            "schools.services.resolve_effective_pickup_time",
            lambda child, date: later,
        )
        assert poll_upcoming_dismissals() == 0
        assert dispatched == []
