"""ChatConsumer tests against the full ASGI stack (JWTAuthMiddleware +
URLRouter), so connect-time auth and message fan-out are exercised end to end.
"""

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from chat.models import ChatMessage, ChatReadReceipt
from config.asgi import application

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def connect(thread, token=None):
    path = f"/ws/chat/{thread.id}/"
    if token:
        path = f"{path}?token={token}"
    communicator = WebsocketCommunicator(application, path)
    connected, close_code = await communicator.connect()
    return communicator, connected, close_code


class TestConnectAuthorization:
    async def test_rejects_missing_token(self, thread):
        communicator, connected, close_code = await connect(thread)
        assert not connected
        assert close_code == 4001
        await communicator.disconnect()

    async def test_rejects_non_member(self, thread, actors, make_token):
        users, _ = actors
        communicator, connected, close_code = await connect(
            thread, make_token(sub=users["d"].clerk_user_id)
        )
        assert not connected
        assert close_code == 4003
        await communicator.disconnect()

    async def test_accepts_member(self, thread, actors, make_token):
        users, _ = actors
        communicator, connected, _ = await connect(
            thread, make_token(sub=users["b"].clerk_user_id)
        )
        assert connected
        await communicator.disconnect()


class TestMessaging:
    async def test_send_broadcasts_and_persists(self, thread, actors, make_token):
        users, _ = actors
        sender, _, _ = await connect(thread, make_token(sub=users["a"].clerk_user_id))
        watcher, _, _ = await connect(thread, make_token(sub=users["b"].clerk_user_id))

        await sender.send_json_to(
            {"type": "message.send", "content": "heads up, running late"}
        )

        event = await watcher.receive_json_from()
        assert event["type"] == "message.new"
        assert event["message"]["content"] == "heads up, running late"
        assert event["message"]["sender"] == str(users["a"].id)

        count = await database_sync_to_async(
            ChatMessage.objects.filter(thread=thread).count
        )()
        assert count == 1

        await sender.disconnect()
        await watcher.disconnect()

    async def test_empty_message_rejected(self, thread, actors, make_token):
        users, _ = actors
        sender, _, _ = await connect(thread, make_token(sub=users["a"].clerk_user_id))
        await sender.send_json_to({"type": "message.send"})
        event = await sender.receive_json_from()
        assert event["type"] == "error"
        count = await database_sync_to_async(
            ChatMessage.objects.filter(thread=thread).count
        )()
        assert count == 0
        await sender.disconnect()

    async def test_read_broadcasts_receipt(self, thread, actors, make_token):
        users, _ = actors
        message = await database_sync_to_async(ChatMessage.objects.create)(
            thread=thread, sender=users["a"], content="hi"
        )
        reader, _, _ = await connect(thread, make_token(sub=users["b"].clerk_user_id))

        await reader.send_json_to(
            {"type": "message.read", "message_id": str(message.id)}
        )
        event = await reader.receive_json_from()
        assert event["type"] == "message.read"
        assert event["up_to_message"] == str(message.id)

        exists = await database_sync_to_async(
            ChatReadReceipt.objects.filter(user=users["b"], message=message).exists
        )()
        assert exists

        await reader.disconnect()
