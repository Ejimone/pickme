"""SOS safety alerts: immediate guardian fan-out (notifications + push + trip
WebSocket), visibility scoping, and resolution.
"""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from config.asgi import application
from notifications import services
from notifications.models import DeviceToken, Notification
from trips.models import SOSAlert

pytestmark = pytest.mark.django_db


def _raise(client, trip, **extra):
    payload = {"trip": str(trip.id), "message": "help!", **extra}
    return client.post("/api/v1/sos-alerts/", payload, format="json")


class TestRaise:
    def test_fans_out_to_guardians_excluding_raiser(self, trip, actors, clients):
        users, _ = actors
        resp = _raise(clients["a"], trip)
        assert resp.status_code == 201
        assert resp.json()["status"] == "active"
        assert SOSAlert.objects.filter(status="active").count() == 1

        # Family B is a guardian on the trip → notified.
        assert Notification.objects.filter(
            user=users["b"], type=Notification.Type.SOS
        ).count() == 1
        # Raiser A knows already → not self-notified.
        assert Notification.objects.filter(
            user=users["a"], type=Notification.Type.SOS
        ).count() == 0
        # Outsider D is not on the trip/group → nothing.
        assert Notification.objects.filter(
            user=users["d"], type=Notification.Type.SOS
        ).count() == 0

    def test_immediate_push_and_delivered(self, trip, actors, clients, monkeypatch):
        users, _ = actors
        DeviceToken.objects.create(
            user=users["b"], token="ExponentPushToken[b]", platform="ios"
        )
        capture = services.FakeExpoPushService()
        monkeypatch.setattr(services, "get_push_client", lambda: capture)

        _raise(clients["a"], trip)

        assert [m["to"] for m in capture.sent] == ["ExponentPushToken[b]"]
        notification = Notification.objects.get(
            user=users["b"], type=Notification.Type.SOS
        )
        assert notification.delivered_at is not None  # pushed in-request

    def test_outsider_cannot_raise(self, trip, clients):
        resp = _raise(clients["d"], trip)
        assert resp.status_code == 400


class TestVisibility:
    def test_list_scoping(self, trip, actors, clients):
        _raise(clients["a"], trip)
        # Guardian and raiser see it; outsider does not.
        assert len(clients["b"].get("/api/v1/sos-alerts/").json()["results"]) == 1
        assert len(clients["a"].get("/api/v1/sos-alerts/").json()["results"]) == 1
        assert len(clients["d"].get("/api/v1/sos-alerts/").json()["results"]) == 0


class TestResolve:
    def test_guardian_resolves(self, trip, actors, clients):
        users, _ = actors
        alert_id = _raise(clients["a"], trip).json()["id"]
        resp = clients["b"].post(f"/api/v1/sos-alerts/{alert_id}/resolve/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"
        assert resp.json()["resolved_by"] == str(users["b"].id)
        # Default list shows only active alerts.
        assert len(clients["b"].get("/api/v1/sos-alerts/").json()["results"]) == 0

    def test_outsider_cannot_resolve(self, trip, clients):
        alert_id = _raise(clients["a"], trip).json()["id"]
        resp = clients["d"].post(f"/api/v1/sos-alerts/{alert_id}/resolve/")
        assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTripBroadcast:
    async def test_sos_broadcasts_to_trip_channel(
        self, trip, actors, make_token, monkeypatch
    ):
        from notifications.tasks import send_push_notification
        from trips.models import SOSAlert
        from trips.sos import fan_out_sos

        # Keep the notification signal's push dispatch off the real broker.
        monkeypatch.setattr(send_push_notification, "delay", lambda *a, **k: None)

        users, _ = actors
        path = f"/ws/trips/{trip.id}/?token={make_token(sub=users['b'].clerk_user_id)}"
        communicator = WebsocketCommunicator(application, path)
        connected, _ = await communicator.connect()
        assert connected

        def _raise_sos():
            alert = SOSAlert.objects.create(
                trip=trip, raised_by=users["a"], message="help!"
            )
            fan_out_sos(alert)
            return alert

        await database_sync_to_async(_raise_sos)()

        event = await communicator.receive_json_from()
        assert event["type"] == "sos_alert"
        assert event["sos"]["message"] == "help!"
        await communicator.disconnect()
