"""Trip-domain services: the Maps ETA client, the ETA-throttle lock, and the
shared ping-recording path used by both the WebSocket consumer and the REST
fallback endpoint.

The Maps client is selected via MAPS_BACKEND ("fake" | "google") so tests and
local dev never hit the real Distance Matrix API.
"""

import redis
import requests
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"


class FakeMapsService:
    """Deterministic ETA for tests/local dev: 60s per 0.01 degree of travel."""

    def eta_seconds(self, origin, destination):
        d_lat = abs(float(origin[0]) - float(destination[0]))
        d_lng = abs(float(origin[1]) - float(destination[1]))
        return int((d_lat + d_lng) * 6000)


class GoogleMapsService:
    def eta_seconds(self, origin, destination):
        response = requests.get(
            DISTANCE_MATRIX_URL,
            params={
                "origins": f"{origin[0]},{origin[1]}",
                "destinations": f"{destination[0]},{destination[1]}",
                "mode": "driving",
                "departure_time": "now",
                "key": settings.GOOGLE_MAPS_API_KEY,
            },
            timeout=10,
        )
        response.raise_for_status()
        element = response.json()["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return None
        duration = element.get("duration_in_traffic") or element["duration"]
        return duration["value"]


def get_maps_client():
    if settings.MAPS_BACKEND == "google":
        return GoogleMapsService()
    return FakeMapsService()


def stop_destination(stop):
    """(lat, lng) of a stop's school or activity, or None if not geocoded."""
    if stop.activity_id and stop.activity.location_lat is not None:
        return (stop.activity.location_lat, stop.activity.location_lng)
    if stop.school_id and stop.school.lat is not None:
        return (stop.school.lat, stop.school.lng)
    return None


def acquire_eta_lock(trip_id):
    """Per-trip throttle: SET NX with TTL, per SYSTEMS-DEEP-DIVE.md.

    Celery's rate_limit is per-task-global; "at most once per 30s per trip"
    needs a keyed lock. If the lock is held, skip — a fresher ping will
    trigger the next recalculation anyway.
    """
    client = redis.Redis.from_url(settings.REDIS_URL)
    return bool(
        client.set(
            f"eta_lock:{trip_id}", "1", nx=True, ex=settings.ETA_THROTTLE_SECONDS
        )
    )


def broadcast_to_trip(trip_id, payload):
    """group_send an event dict (must carry a `type` handler key) to the
    trip's channel group."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(f"trip_{trip_id}", payload)


def record_ping(trip, data):
    """Write a LocationPing, broadcast it immediately, and conditionally
    dispatch ETA recalculation. Shared by TripConsumer and the REST fallback.

    `data` carries lat/lng and optional speed/heading/recorded_at.
    Broadcast never waits on the ETA task — position updates stay instant.
    """
    from trips.models import LocationPing
    from trips.tasks import recalculate_trip_eta

    recorded_at = data.get("recorded_at")
    if isinstance(recorded_at, str):  # WS payloads carry ISO strings
        recorded_at = parse_datetime(recorded_at)
    ping = LocationPing.objects.create(
        trip=trip,
        lat=data["lat"],
        lng=data["lng"],
        speed=data.get("speed"),
        heading=data.get("heading"),
        recorded_at=recorded_at or timezone.now(),
    )
    broadcast_to_trip(
        trip.id,
        {
            "type": "location_update",
            "trip_id": str(trip.id),
            "lat": str(ping.lat),
            "lng": str(ping.lng),
            "speed": ping.speed,
            "heading": ping.heading,
            "recorded_at": ping.recorded_at.isoformat(),
        },
    )
    if acquire_eta_lock(trip.id):
        recalculate_trip_eta.delay(str(trip.id))
    return ping
