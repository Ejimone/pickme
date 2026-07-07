from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsFamilyMember
from trips.models import PickupEvent, SOSAlert, Trip, TripStop
from trips.permissions import IsTripDriver, IsTripParticipant, trips_visible_to
from trips.serializers import (
    LocationPingSerializer,
    PickupEventSerializer,
    SOSAlertCreateSerializer,
    SOSAlertSerializer,
    TripCreateSerializer,
    TripSerializer,
    TripStopSerializer,
    TripStopUpdateSerializer,
)
from trips.services import broadcast_to_trip, record_ping

# Allowed TripStop transitions per the lifecycle in SYSTEMS-DEEP-DIVE.md
STOP_TRANSITIONS = {
    TripStop.Status.PENDING: {TripStop.Status.EN_ROUTE, TripStop.Status.SKIPPED},
    TripStop.Status.EN_ROUTE: {TripStop.Status.ARRIVED, TripStop.Status.SKIPPED},
    TripStop.Status.ARRIVED: {TripStop.Status.PICKED_UP},
}


class TripViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TripSerializer
    permission_classes = [IsAuthenticated, IsTripParticipant]

    def get_queryset(self):
        qs = (
            Trip.objects.filter(trips_visible_to(self.request.user))
            .distinct()
            .prefetch_related("stops__children__child")
            .order_by("-date", "-created_at")
        )
        date = self.request.query_params.get("date")
        if date:
            qs = qs.filter(date=date)
        carpool_group = self.request.query_params.get("carpool_group")
        if carpool_group:
            qs = qs.filter(carpool_group_id=carpool_group)
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return TripCreateSerializer
        return TripSerializer

    def _get_trip_as_driver(self, request):
        trip = self.get_object()
        if trip.driver_id != request.user.id:
            raise PermissionDenied(IsTripDriver.message)
        return trip

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        trip = self._get_trip_as_driver(request)
        if trip.status != Trip.Status.NOT_STARTED:
            raise ValidationError(f"Cannot start a trip that is {trip.status}.")
        trip.status = Trip.Status.IN_PROGRESS
        trip.started_at = timezone.now()
        trip.save(update_fields=["status", "started_at"])
        trip.stops.filter(status=TripStop.Status.PENDING).update(
            status=TripStop.Status.EN_ROUTE
        )
        broadcast_to_trip(
            trip.id,
            {
                "type": "trip_status_update",
                "trip_id": str(trip.id),
                "status": trip.status,
            },
        )
        return Response(TripSerializer(trip).data)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        trip = self._get_trip_as_driver(request)
        if trip.status != Trip.Status.IN_PROGRESS:
            raise ValidationError(f"Cannot end a trip that is {trip.status}.")
        trip.status = Trip.Status.COMPLETED
        trip.ended_at = timezone.now()
        trip.save(update_fields=["status", "ended_at"])
        broadcast_to_trip(
            trip.id,
            {
                "type": "trip_status_update",
                "trip_id": str(trip.id),
                "status": trip.status,
            },
        )
        return Response(TripSerializer(trip).data)

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"stops/(?P<stop_id>[^/.]+)",
        url_name="stop-update",
    )
    def update_stop(self, request, pk=None, stop_id=None):
        trip = self._get_trip_as_driver(request)
        try:
            stop = trip.stops.get(id=stop_id)
        except (TripStop.DoesNotExist, DjangoValidationError, ValueError):
            raise NotFound("Stop not found on this trip.")

        serializer = TripStopUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
        subset = serializer.validated_data.get("children")

        if new_status not in STOP_TRANSITIONS.get(stop.status, set()):
            raise ValidationError(
                f"Cannot move a {stop.status} stop to {new_status}."
            )

        stop.status = new_status
        update_fields = ["status"]
        if new_status == TripStop.Status.ARRIVED:
            stop.actual_arrival_time = timezone.now()
            update_fields.append("actual_arrival_time")
        stop.save(update_fields=update_fields)

        if new_status == TripStop.Status.PICKED_UP:
            entries = stop.children.filter(picked_up_at__isnull=True)
            if subset:
                entries = entries.filter(child__in=subset)
            now = timezone.now()
            # Individual saves so the post_save cascade signal fires per child
            for entry in entries:
                entry.picked_up_at = now
                entry.save(update_fields=["picked_up_at"])

        broadcast_to_trip(
            trip.id,
            {
                "type": "stop_status_update",
                "trip_id": str(trip.id),
                "stop_id": str(stop.id),
                "status": stop.status,
                "eta": stop.eta.isoformat() if stop.eta else None,
            },
        )
        return Response(TripStopSerializer(stop).data)

    @action(detail=True, methods=["post"])
    def location(self, request, pk=None):
        """REST fallback ping — primary path is the WebSocket; this exists
        for spotty-connectivity retries."""
        trip = self._get_trip_as_driver(request)
        if trip.status != Trip.Status.IN_PROGRESS:
            raise ValidationError("Trip is not in progress.")
        serializer = LocationPingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ping = record_ping(trip, serializer.validated_data)
        return Response(
            LocationPingSerializer(ping).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="location/latest")
    def latest_location(self, request, pk=None):
        trip = self.get_object()
        ping = trip.pings.order_by("-recorded_at").first()
        if ping is None:
            raise NotFound("No location recorded for this trip yet.")
        return Response(LocationPingSerializer(ping).data)


class PickupEventViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """The "Today" view — one PickupEvent row per child across all of a
    family's children/schools — plus manual status/method overrides."""

    serializer_class = PickupEventSerializer
    permission_classes = [IsFamilyMember]
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        qs = (
            PickupEvent.objects.filter(
                child__family__members__user=self.request.user
            )
            .select_related("child")
            .distinct()
            .order_by("scheduled_time", "child__full_name")
        )
        family = self.request.query_params.get("family")
        if family:
            qs = qs.filter(child__family_id=family)
        date = self.request.query_params.get("date")
        if self.action == "list":
            # "Today" semantics: default to today when no date is given.
            qs = qs.filter(date=date or timezone.localdate())
        elif date:
            qs = qs.filter(date=date)
        return qs


class SOSAlertViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Raise/list/resolve emergency alerts. Raising fans out immediately to
    every guardian on the trip (see trips.sos.fan_out_sos)."""

    serializer_class = SOSAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Alerts on a trip the user can see, or ones they raised themselves.
        qs = SOSAlert.objects.filter(
            Q(trip__in=Trip.objects.filter(trips_visible_to(self.request.user)))
            | Q(raised_by=self.request.user)
        ).distinct().select_related("trip", "raised_by")
        status_filter = self.request.query_params.get("status", "active")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return SOSAlertCreateSerializer
        return SOSAlertSerializer

    def create(self, request, *args, **kwargs):
        from trips.sos import fan_out_sos

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert = serializer.save(raised_by=request.user)
        fan_out_sos(alert)
        return Response(
            SOSAlertSerializer(alert).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        if alert.status == SOSAlert.Status.RESOLVED:
            return Response(SOSAlertSerializer(alert).data)
        alert.status = SOSAlert.Status.RESOLVED
        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user
        alert.save(update_fields=["status", "resolved_at", "resolved_by"])
        return Response(SOSAlertSerializer(alert).data)
