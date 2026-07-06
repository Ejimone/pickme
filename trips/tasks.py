import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from trips.models import LocationPing, Trip, TripStop

CLEANUP_BATCH_SIZE = 5000


@shared_task(
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    max_retries=3,
)
def recalculate_trip_eta(trip_id):
    """Update the next stop's ETA from the latest ping via Distance Matrix.

    Throttling happens at the dispatch site (per-trip Redis lock in
    trips.services.record_ping), not here — see SYSTEMS-DEEP-DIVE.md.
    """
    from trips.services import broadcast_to_trip, get_maps_client, stop_destination

    trip = (
        Trip.objects.filter(id=trip_id, status=Trip.Status.IN_PROGRESS)
        .prefetch_related("stops")
        .first()
    )
    if trip is None:
        return None

    ping = trip.pings.order_by("-recorded_at").first()
    if ping is None:
        return None

    next_stop = trip.stops.filter(
        status__in=[TripStop.Status.PENDING, TripStop.Status.EN_ROUTE]
    ).first()  # stops are ordered by sequence_order
    if next_stop is None:
        return None

    destination = stop_destination(next_stop)
    if destination is None:
        return None

    seconds = get_maps_client().eta_seconds((ping.lat, ping.lng), destination)
    if seconds is None:
        return None

    next_stop.eta = timezone.now() + timezone.timedelta(seconds=seconds)
    next_stop.save(update_fields=["eta"])

    broadcast_to_trip(
        trip.id,
        {
            "type": "trip_status_update",
            "trip_id": str(trip.id),
            "status": trip.status,
            "stop_id": str(next_stop.id),
            "eta": next_stop.eta.isoformat(),
        },
    )
    return next_stop.eta.isoformat()


@shared_task
def cleanup_old_location_pings():
    """Nightly beat task. Batched deletes (5k rows) to avoid long locks on a
    high-volume table; naturally idempotent."""
    cutoff = timezone.now() - timezone.timedelta(
        days=settings.LOCATION_PING_RETENTION_DAYS
    )
    total = 0
    while True:
        batch = list(
            LocationPing.objects.filter(recorded_at__lt=cutoff).values_list(
                "id", flat=True
            )[:CLEANUP_BATCH_SIZE]
        )
        if not batch:
            break
        deleted, _ = LocationPing.objects.filter(id__in=batch).delete()
        total += deleted
    return total
