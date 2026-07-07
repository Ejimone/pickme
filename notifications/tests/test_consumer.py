"""NotificationConsumer against the full ASGI stack: connect-time auth (you
may only subscribe to your own stream) and `notification.new` fan-out.
"""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from config.asgi import application
from notifications.models import Notification
from notifications.services import create_notification

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def no_push_dispatch(monkeypatch):
    from notifications.tasks import send_push_notification

    monkeypatch.setattr(send_push_notification, "delay", lambda *a, **k: None)


async def connect(user_id, token=None):
    path = f"/ws/notifications/{user_id}/"
    if token:
        path = f"{path}?token={token}"
    communicator = WebsocketCommunicator(application, path)
    connected, close_code = await communicator.connect()
    return communicator, connected, close_code


class TestConnectAuthorization:
    async def test_rejects_missing_token(self, actors):
        users, _ = actors
        communicator, connected, close_code = await connect(users["a"].id)
        assert not connected
        assert close_code == 4001
        await communicator.disconnect()

    async def test_rejects_other_users_stream(self, actors, make_token):
        users, _ = actors
        communicator, connected, close_code = await connect(
            users["b"].id, make_token(sub=users["a"].clerk_user_id)
        )
        assert not connected
        assert close_code == 4003
        await communicator.disconnect()

    async def test_accepts_own_stream(self, actors, make_token):
        users, _ = actors
        communicator, connected, _ = await connect(
            users["a"].id, make_token(sub=users["a"].clerk_user_id)
        )
        assert connected
        await communicator.disconnect()


class TestFanOut:
    async def test_receives_new_notification(self, actors, make_token):
        users, _ = actors
        communicator, connected, _ = await connect(
            users["a"].id, make_token(sub=users["a"].clerk_user_id)
        )
        assert connected

        await database_sync_to_async(create_notification)(
            user=users["a"],
            type=Notification.Type.CHAT_MESSAGE,
            title="New message",
            body="running late",
        )

        event = await communicator.receive_json_from()
        assert event["type"] == "notification.new"
        assert event["notification"]["title"] == "New message"
        await communicator.disconnect()
