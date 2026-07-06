"""REST surface: notification list/read, preference toggles, device tokens.

Scoping bar: a user only ever sees their own notifications and tokens.
"""

import pytest

from notifications.models import DeviceToken, Notification, NotificationPreference
from notifications.services import create_notification

pytestmark = pytest.mark.django_db


def _make_notif(user, **kwargs):
    notification, _ = create_notification(
        user=user,
        type=Notification.Type.CHAT_MESSAGE,
        title=kwargs.get("title", "Hi"),
        body=kwargs.get("body", "there"),
    )
    return notification


class TestNotificationList:
    def test_lists_only_own_notifications(self, actors, clients):
        users, _ = actors
        _make_notif(users["a"])
        _make_notif(users["b"])
        resp = clients["a"].get("/api/v1/notifications/")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1

    def test_is_read_filter(self, actors, clients):
        users, _ = actors
        read = _make_notif(users["a"])
        read.is_read = True
        read.save(update_fields=["is_read"])
        _make_notif(users["a"])  # unread

        resp = clients["a"].get("/api/v1/notifications/?is_read=false")
        assert len(resp.json()["results"]) == 1
        assert resp.json()["results"][0]["is_read"] is False

    def test_mark_read(self, actors, clients):
        users, _ = actors
        notification = _make_notif(users["a"])
        resp = clients["a"].post(f"/api/v1/notifications/{notification.id}/read/")
        assert resp.status_code == 200
        assert resp.json()["is_read"] is True
        notification.refresh_from_db()
        assert notification.is_read is True

    def test_cannot_read_another_users_notification(self, actors, clients):
        users, _ = actors
        notification = _make_notif(users["b"])
        resp = clients["a"].post(f"/api/v1/notifications/{notification.id}/read/")
        assert resp.status_code == 404


class TestPreferences:
    def test_list_returns_a_row_per_type(self, clients):
        resp = clients["a"].get("/api/v1/notification-preferences/")
        assert resp.status_code == 200
        types = {row["notification_type"] for row in resp.json()}
        assert types == set(Notification.Type.values)

    def test_patch_materializes_and_updates(self, actors, clients):
        users, _ = actors
        resp = clients["a"].patch(
            "/api/v1/notification-preferences/pickup_reminder/",
            {"push_enabled": False},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["push_enabled"] is False
        pref = NotificationPreference.objects.get(
            user=users["a"], notification_type="pickup_reminder"
        )
        assert pref.push_enabled is False

    def test_patch_unknown_type_404(self, clients):
        resp = clients["a"].patch(
            "/api/v1/notification-preferences/not_a_type/",
            {"push_enabled": False},
            format="json",
        )
        assert resp.status_code == 404


class TestDeviceTokens:
    def test_register_and_delete(self, actors, clients):
        users, _ = actors
        resp = clients["a"].post(
            "/api/v1/device-tokens/",
            {"token": "ExponentPushToken[abc]", "platform": "ios"},
            format="json",
        )
        assert resp.status_code == 201
        token_id = resp.json()["id"]
        assert DeviceToken.objects.filter(user=users["a"]).count() == 1

        resp = clients["a"].delete(f"/api/v1/device-tokens/{token_id}/")
        assert resp.status_code == 204
        assert DeviceToken.objects.filter(user=users["a"]).count() == 0

    def test_reregister_rebinds_token(self, actors, clients):
        users, _ = actors
        DeviceToken.objects.create(
            user=users["b"], token="ExponentPushToken[xyz]", platform="android"
        )
        resp = clients["a"].post(
            "/api/v1/device-tokens/",
            {"token": "ExponentPushToken[xyz]", "platform": "ios"},
            format="json",
        )
        assert resp.status_code == 201
        token = DeviceToken.objects.get(token="ExponentPushToken[xyz]")
        assert token.user_id == users["a"].id
        assert token.platform == "ios"

    def test_cannot_delete_another_users_token(self, actors, clients):
        users, _ = actors
        token = DeviceToken.objects.create(
            user=users["b"], token="ExponentPushToken[b]", platform="ios"
        )
        resp = clients["a"].delete(f"/api/v1/device-tokens/{token.id}/")
        assert resp.status_code == 404
