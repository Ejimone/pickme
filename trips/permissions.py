"""Trip-scoped access control.

A user may watch a trip if they are its driver, a member of a family with a
child in one of its stops, or a member of its carpool group (per
SYSTEMS-DEEP-DIVE.md connect-time authorization). Only the driver may mutate.
"""

from django.db.models import Q
from rest_framework.permissions import BasePermission


def trips_visible_to(user):
    """Q filter selecting trips the user is allowed to see. Shared by the
    viewset queryset and the WebSocket consumer's connect check."""
    return (
        Q(driver=user)
        | Q(stops__children__child__family__members__user=user)
        | Q(carpool_group__members__family__members__user=user)
    )


def user_can_access_trip(user, trip_id):
    from trips.models import Trip

    return Trip.objects.filter(trips_visible_to(user), id=trip_id).exists()


class IsTripParticipant(BasePermission):
    message = "You do not have access to this trip."

    def has_object_permission(self, request, view, obj):
        trip = obj if not hasattr(obj, "trip_id") else obj.trip
        return user_can_access_trip(request.user, trip.id)


class IsTripDriver(BasePermission):
    message = "Only the trip's driver can do this."

    def has_object_permission(self, request, view, obj):
        trip = obj if not hasattr(obj, "trip_id") else obj.trip
        return trip.driver_id == request.user.id
