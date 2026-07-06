"""Per-user in-app notification stream (`ws/notifications/{user_id}/`).

Read-only: the client never sends events. Connect-time authorization requires
the authenticated user to match the `{user_id}` in the path — you can only
subscribe to your own stream. Notifications are pushed by a signal on
`Notification.save()` (see notifications.signals), never by consumer logic.
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer

CLOSE_UNAUTHENTICATED = 4001
CLOSE_FORBIDDEN = 4003


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user_id = self.scope["url_route"]["kwargs"]["user_id"]
        self.group_name = f"user_{self.user_id}"
        user = self.scope["user"]

        if not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if str(user.id) != str(self.user_id):
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
        # Read-only stream — reject any client-sent event.
        await self.send_json(
            {"type": "error", "message": "This stream is read-only."}
        )

    # --- group event handler (server → this user's devices) ---

    async def notification_new(self, event):
        await self.send_json(event)
