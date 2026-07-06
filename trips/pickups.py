"""PickupEvent generation and the trip→pickup status cascade.

Signals stay thin (per the working rules) and delegate here. Everything is
idempotent — keyed on the (child, date) unique constraint — so trip starts,
daily beat runs, and re-saves never create duplicates.
"""

from django.utils import timezone

from carpool.models import CarpoolAssignment
from families.models import Child
from schools.services import resolve_effective_pickup_time
from trips.models import PickupEvent, TripStop, TripStopChild


def _carpool_assignment_for(child, date):
    """A live (non-cancelled) carpool assignment covering this child on this
    date, if the child's family carpools at the child's school."""
    if child.school_id is None:
        return None
    return (
        CarpoolAssignment.objects.filter(
            date=date,
            carpool_group__school_id=child.school_id,
            carpool_group__members__family_id=child.family_id,
        )
        .exclude(status=CarpoolAssignment.Status.CANCELLED)
        .first()
    )


def ensure_pickup_event(child, date, *, trip_stop_child=None, defaults=None):
    """get_or_create the (child, date) row, filling method/assignment/time.

    Never downgrades an existing row; only backfills the trip link and a
    scheduled_time when they're still empty."""
    assignment = _carpool_assignment_for(child, date)
    base_defaults = {
        "scheduled_time": resolve_effective_pickup_time(child, date),
    }
    if assignment is not None:
        base_defaults["pickup_method"] = PickupEvent.Method.CARPOOL
        base_defaults["carpool_assignment"] = assignment
    if trip_stop_child is not None:
        base_defaults["trip_stop_child"] = trip_stop_child
    base_defaults.update(defaults or {})

    event, created = PickupEvent.objects.get_or_create(
        child=child, date=date, defaults=base_defaults
    )
    if not created:
        dirty = []
        if trip_stop_child is not None and event.trip_stop_child_id is None:
            event.trip_stop_child = trip_stop_child
            dirty.append("trip_stop_child")
        if event.scheduled_time is None and base_defaults["scheduled_time"]:
            event.scheduled_time = base_defaults["scheduled_time"]
            dirty.append("scheduled_time")
        if dirty:
            event.save(update_fields=dirty)
    return event


def ensure_pickup_events_for_trip(trip):
    """Called when a trip goes in_progress: one PickupEvent per child on the
    trip, linked to its TripStopChild and moved to en_route."""
    entries = TripStopChild.objects.filter(trip_stop__trip=trip).select_related(
        "child"
    )
    for entry in entries:
        defaults = {"status": PickupEvent.Status.EN_ROUTE}
        if trip.carpool_group_id:  # a trip on a group is a carpool run
            defaults["pickup_method"] = PickupEvent.Method.CARPOOL
        ensure_pickup_event(
            entry.child,
            trip.date,
            trip_stop_child=entry,
            defaults=defaults,
        )


def sync_stop_status(stop):
    """Propagate a TripStop's en_route/arrived status onto the linked
    children's PickupEvents (picked_up is handled per-child below)."""
    mapping = {
        TripStop.Status.EN_ROUTE: PickupEvent.Status.EN_ROUTE,
        TripStop.Status.ARRIVED: PickupEvent.Status.ARRIVED,
    }
    new_status = mapping.get(stop.status)
    if new_status is None:
        return
    PickupEvent.objects.filter(
        trip_stop_child__trip_stop=stop
    ).exclude(status=PickupEvent.Status.PICKED_UP).update(status=new_status)


def mark_child_picked_up(trip_stop_child):
    """The Stage-4 cascade trigger: TripStopChild.picked_up_at set → the
    linked PickupEvent flips to picked_up. Ensures the row exists first."""
    event = ensure_pickup_event(
        trip_stop_child.child,
        trip_stop_child.trip_stop.trip.date,
        trip_stop_child=trip_stop_child,
    )
    if event.status != PickupEvent.Status.PICKED_UP:
        event.status = PickupEvent.Status.PICKED_UP
        event.save(update_fields=["status"])
    return event


def generate_daily_pickup_events(date):
    """Beat task body: ensure a PickupEvent for every active child that has a
    resolvable pickup that day. Returns the count created."""
    created = 0
    children = Child.objects.filter(is_active=True, school__isnull=False)
    for child in children.select_related("school", "family"):
        if resolve_effective_pickup_time(child, date) is None:
            continue  # no school and no activity — nothing to pick up
        existed = PickupEvent.objects.filter(child=child, date=date).exists()
        ensure_pickup_event(child, date)
        if not existed:
            created += 1
    return created
