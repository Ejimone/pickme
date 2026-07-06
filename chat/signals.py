"""Auto-create the standing chat thread for each carpool group and the
"today's run" thread for each trip. Thin: get_or_create only, so it's safe to
fire on every save.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from carpool.models import CarpoolGroup
from chat.models import ChatThread
from trips.models import Trip


@receiver(post_save, sender=CarpoolGroup)
def create_group_thread(sender, instance, created, **kwargs):
    if created:
        ChatThread.objects.get_or_create(
            carpool_group=instance,
            context_type=ChatThread.ContextType.CARPOOL_GROUP,
        )


@receiver(post_save, sender=Trip)
def create_trip_thread(sender, instance, created, **kwargs):
    if created:
        ChatThread.objects.get_or_create(
            trip=instance,
            context_type=ChatThread.ContextType.TRIP,
            defaults={"carpool_group": instance.carpool_group},
        )
