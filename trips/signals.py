"""Cascade hooks for trip tracking, kept thin per the working rules — each
receiver just delegates to trips.pickups.

Chain (SYSTEMS-DEEP-DIVE.md §4):
  Trip → in_progress            → ensure a PickupEvent per child (en_route)
  TripStop → en_route/arrived   → propagate status onto linked PickupEvents
  TripStopChild.picked_up_at set → linked PickupEvent → picked_up
The Notification fan-out on picked_up lands in Stage 7.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from trips import pickups
from trips.models import Trip, TripStop, TripStopChild


@receiver(post_save, sender=Trip)
def on_trip_saved(sender, instance, **kwargs):
    if instance.status == Trip.Status.IN_PROGRESS:
        pickups.ensure_pickup_events_for_trip(instance)


@receiver(post_save, sender=TripStop)
def on_trip_stop_saved(sender, instance, created, **kwargs):
    if not created:
        pickups.sync_stop_status(instance)


@receiver(post_save, sender=TripStopChild)
def on_trip_stop_child_saved(sender, instance, created, **kwargs):
    if created or instance.picked_up_at is None:
        return
    pickups.mark_child_picked_up(instance)
