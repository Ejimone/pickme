"""Chat room for one thread (`ws/chat/{thread_id}/`).

Connect-time authorization (before group_add): the user's family is a member
of the thread's carpool group, or the user is party to the thread's trip.
Any participant may send. The consumer only writes to chat tables.
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from chat.services import mark_read, post_message, user_can_access_thread

CLOSE_UNAUTHENTICATED = 4001
CLOSE_FORBIDDEN = 4003


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.thread_id = self.scope["url_route"]["kwargs"]["thread_id"]
        self.group_name = f"chat_{self.thread_id}"
        user = self.scope["user"]

        if not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if not await database_sync_to_async(user_can_access_thread)(
            user, self.thread_id
        ):
            await self.close(code=CLOSE_FORBIDDEN)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )

    async def receive_json(self, content, **kwargs):
        event_type = content.get("type")
        if event_type == "message.send":
            await self.handle_send(content)
        elif event_type == "message.read":
            await self.handle_read(content)
        else:
            await self.send_json(
                {"type": "error", "message": f"Unknown event type: {event_type}"}
            )

    async def _get_thread(self):
        from chat.models import ChatThread

        return await database_sync_to_async(
            lambda: ChatThread.objects.filter(id=self.thread_id).first()
        )()

    async def handle_send(self, content):
        if not content.get("content") and not content.get("attachment_url"):
            await self.send_json(
                {"type": "error", "message": "A message needs content or an attachment."}
            )
            return
        thread = await self._get_thread()
        # post_message writes the row and group_sends message.new to everyone.
        await database_sync_to_async(post_message)(
            thread, self.scope["user"], content
        )

    async def handle_read(self, content):
        from chat.models import ChatMessage

        thread = await self._get_thread()
        message = await database_sync_to_async(
            lambda: ChatMessage.objects.filter(
                thread=thread, id=content.get("message_id")
            ).first()
        )()
        if message is None:
            await self.send_json(
                {"type": "error", "message": "Message not found in this thread."}
            )
            return
        await database_sync_to_async(mark_read)(
            thread, self.scope["user"], message
        )

    # --- group event handlers (server → all thread participants) ---
    # Channels maps the dotted event type to these method names.

    async def message_new(self, event):
        await self.send_json(event)

    async def message_read(self, event):
        await self.send_json(event)
