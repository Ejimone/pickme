from celery import shared_task
from django.conf import settings
from django.utils import timezone

from carpool.models import CarpoolAssignment, CarpoolSwapRequest


@shared_task
def expire_stale_swap_requests():
    """Hourly beat task. Naturally idempotent (bulk status filters)."""
    cutoff = timezone.now() - timezone.timedelta(
        hours=settings.SWAP_REQUEST_EXPIRY_HOURS
    )
    stale = CarpoolSwapRequest.objects.filter(
        status=CarpoolSwapRequest.Status.PENDING, created_at__lt=cutoff
    )
    assignment_ids = list(stale.values_list("assignment_id", flat=True))
    expired_count = stale.update(
        status=CarpoolSwapRequest.Status.EXPIRED, resolved_at=timezone.now()
    )

    # Release the affected assignments from swap_pending limbo.
    affected = CarpoolAssignment.objects.filter(
        id__in=assignment_ids,
        status=CarpoolAssignment.Status.SWAP_PENDING,
    )
    affected.filter(driver_user__isnull=False).update(
        status=CarpoolAssignment.Status.CONFIRMED
    )
    affected.filter(driver_user__isnull=True).update(
        status=CarpoolAssignment.Status.SUGGESTED
    )
    return expired_count
