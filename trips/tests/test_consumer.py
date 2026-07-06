"""WebSocket consumer tests, run against the full ASGI stack
(JWTAuthMiddleware + URLRouter) so connect-time auth is tested end to end.
"""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from config.asgi import application
from trips.models import LocationPing

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


def ws_path(trip, token=None):
    path = f"/ws/trips/{trip.id}/"
    return f"{path}?token={token}" if token else path


async def connect(trip, token=None):
    communicator = WebsocketCommunicator(application, ws_path(trip, token))
    connected, close_code = await communicator.connect()
    return communicator, connected, close_code


class TestConnectAuthorization:
    async def test_rejects_missing_token(self, trip):
        communicator, connected, close_code = await connect(trip)
        assert not connected
        assert close_code == 4001
        await communicator.disconnect()

    async def test_rejects_invalid_token(self, trip, make_token):
        communicator, connected, close_code = await connect(
            trip, make_token(exp_offset=-100)  # expired
        )
        assert not connected
        assert close_code == 4001
        await communicator.disconnect()

    async def test_rejects_non_member(self, trip, actors, make_token):
        users, _ = actors
        communicator, connected, close_code = await connect(
            trip, make_token(sub=users["d"].clerk_user_id)
        )
        assert not connected
        assert close_code == 4003
        await communicator.disconnect()

    async def test_accepts_group_member(self, trip, actors, make_token):
        users, _ = actors
        communicator, connected, _ = await connect(
            trip, make_token(sub=users["b"].clerk_user_id)
        )
        assert connected
        await communicator.disconnect()


class TestLocationUpdates:
    async def test_driver_ping_broadcast_and_persisted(
        self, trip, actors, make_token
    ):
        users, _ = actors
        driver, _, _ = await connect(trip, make_token(sub=users["a"].clerk_user_id))
        watcher, _, _ = await connect(trip, make_token(sub=users["b"].clerk_user_id))

        await driver.send_json_to(
            {
                "type": "location_update",
                "lat": "41.878100",
                "lng": "-87.629800",
                "speed": 8.2,
                "heading": 134.0,
                "recorded_at": "2026-07-06T14:32:10Z",
            }
        )

        event = await watcher.receive_json_from()
        assert event["type"] == "location_update"
        assert event["trip_id"] == str(trip.id)
        assert event["lat"] == "41.878100"

        count = await database_sync_to_async(
            LocationPing.objects.filter(trip=trip).count
        )()
        assert count == 1

        await driver.disconnect()
        await watcher.disconnect()

    async def test_non_driver_location_update_rejected(
        self, trip, actors, make_token
    ):
        users, _ = actors
        watcher, _, _ = await connect(trip, make_token(sub=users["b"].clerk_user_id))

        await watcher.send_json_to(
            {"type": "location_update", "lat": "41.0", "lng": "-87.0"}
        )
        event = await watcher.receive_json_from()
        assert event["type"] == "error"

        count = await database_sync_to_async(
            LocationPing.objects.filter(trip=trip).count
        )()
        assert count == 0

        await watcher.disconnect()


class TestStopStatusUpdates:
    async def test_driver_stop_update_broadcast(self, trip, actors, make_token):
        users, _ = actors
        stop = await database_sync_to_async(
            lambda: trip.stops.get()
        )()
        await database_sync_to_async(
            lambda: trip.stops.update(status="en_route")
        )()

        driver, _, _ = await connect(trip, make_token(sub=users["a"].clerk_user_id))
        watcher, _, _ = await connect(trip, make_token(sub=users["b"].clerk_user_id))

        await driver.send_json_to(
            {
                "type": "stop_status_update",
                "stop_id": str(stop.id),
                "status": "arrived",
            }
        )
        event = await watcher.receive_json_from()
        assert event["type"] == "stop_status_update"
        assert event["stop_id"] == str(stop.id)
        assert event["status"] == "arrived"

        await driver.disconnect()
        await watcher.disconnect()
