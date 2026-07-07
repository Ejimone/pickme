"""Live-tracking room for one trip (`ws/trips/{trip_id}/`).

Authorization happens on connect, before group_add: the user must be the
trip's driver, in a family with a child at one of its stops, or a member of
its carpool group. Only the driver may send events. The consumer writes only
to the ping/status tables — data cascades go through signals.
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from trips.models import Trip, TripStop
from trips.permissions import user_can_access_trip
from trips.services import record_ping
from trips.views import STOP_TRANSITIONS

CLOSE_UNAUTHENTICATED = 4001
CLOSE_FORBIDDEN = 4003


class TripConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.trip_id = self.scope["url_route"]["kwargs"]["trip_id"]
        self.group_name = f"trip_{self.trip_id}"
        user = self.scope["user"]

        if not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if not await database_sync_to_async(user_can_access_trip)(
            user, self.trip_id
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
        if event_type == "location_update":
            await self.handle_location_update(content)
        elif event_type == "stop_status_update":
            await self.handle_stop_status_update(content)
        else:
            await self.send_json(
                {"type": "error", "message": f"Unknown event type: {event_type}"}
            )

    async def _get_trip_if_driver(self):
        trip = await database_sync_to_async(
            lambda: Trip.objects.filter(id=self.trip_id).first()
        )()
        if trip is None or trip.driver_id != self.scope["user"].id:
            await self.send_json(
                {"type": "error", "message": "Only the trip's driver can send this."}
            )
            return None
        return trip

    async def handle_location_update(self, content):
        trip = await self._get_trip_if_driver()
        if trip is None:
            return
        try:
            data = {
                "lat": content["lat"],
                "lng": content["lng"],
                "speed": content.get("speed"),
                "heading": content.get("heading"),
                "recorded_at": content.get("recorded_at"),
            }
        except KeyError as exc:
            await self.send_json(
                {"type": "error", "message": f"Missing field: {exc}"}
            )
            return
        # record_ping writes the ping, group_sends it immediately, and
        # dispatches the ETA task only if the per-trip Redis lock is free.
        await database_sync_to_async(record_ping)(trip, data)

    async def handle_stop_status_update(self, content):
        trip = await self._get_trip_if_driver()
        if trip is None:
            return
        result = await database_sync_to_async(self._apply_stop_update)(
            trip, content.get("stop_id"), content.get("status")
        )
        if result is None:
            await self.send_json(
                {"type": "error", "message": "Invalid stop or status transition."}
            )
            return
        await self.channel_layer.group_send(self.group_name, result)

    def _apply_stop_update(self, trip, stop_id, new_status):
        try:
            stop = trip.stops.get(id=stop_id)
        except (TripStop.DoesNotExist, DjangoValidationError, ValueError):
            return None
        if new_status not in STOP_TRANSITIONS.get(stop.status, set()):
            return None

        stop.status = new_status
        update_fields = ["status"]
        if new_status == TripStop.Status.ARRIVED:
            stop.actual_arrival_time = timezone.now()
            update_fields.append("actual_arrival_time")
        stop.save(update_fields=update_fields)

        if new_status == TripStop.Status.PICKED_UP:
            now = timezone.now()
            # Individual saves so the post_save cascade signal fires per child
            for entry in stop.children.filter(picked_up_at__isnull=True):
                entry.picked_up_at = now
                entry.save(update_fields=["picked_up_at"])

        return {
            "type": "stop_status_update",
            "trip_id": str(trip.id),
            "stop_id": str(stop.id),
            "status": stop.status,
            "eta": stop.eta.isoformat() if stop.eta else None,
        }

    # --- group event handlers (server → all trip watchers) ---

    async def location_update(self, event):
        await self.send_json(event)

    async def stop_status_update(self, event):
        await self.send_json(event)

    async def trip_status_update(self, event):
        await self.send_json(event)

    async def sos_alert(self, event):
        # Emergency broadcast pushed by trips.sos.fan_out_sos — watchers with
        # the live map open see it instantly on the trip channel.
        await self.send_json(event)
