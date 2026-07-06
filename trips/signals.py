"""Cascade hooks for trip tracking, kept thin per the working rules.

The full cascade — TripStopChild.picked_up_at → PickupEvent.status →
Notification fan-out — activates in Stages 5 and 7 when those models exist.
This receiver is the anchor point so the consumer/views never write beyond
the ping/status tables directly.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from trips.models import TripStopChild


@receiver(post_save, sender=TripStopChild)
def on_trip_stop_child_saved(sender, instance, created, **kwargs):
    if created or instance.picked_up_at is None:
        return
    # Stage 5: update the linked PickupEvent to picked_up.
    # Stage 7: create Notifications for the child's family members.
