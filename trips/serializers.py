from django.db.models import Q
from rest_framework import serializers

from families.models import Child
from trips.models import (
    LocationPing,
    PickupEvent,
    SOSAlert,
    Trip,
    TripStop,
    TripStopChild,
)


def children_visible_to(user):
    """Children in the user's own families or in families sharing a carpool
    group with one of the user's families."""
    return Child.objects.filter(
        Q(family__members__user=user)
        | Q(
            family__carpool_memberships__carpool_group__members__family__members__user=user
        )
    ).distinct()


class TripStopChildSerializer(serializers.ModelSerializer):
    child_name = serializers.CharField(source="child.full_name", read_only=True)

    class Meta:
        model = TripStopChild
        fields = ["id", "child", "child_name", "picked_up_at"]
        read_only_fields = ["picked_up_at"]


class TripStopSerializer(serializers.ModelSerializer):
    children = TripStopChildSerializer(many=True, read_only=True)

    class Meta:
        model = TripStop
        fields = [
            "id",
            "school",
            "activity",
            "sequence_order",
            "eta",
            "status",
            "actual_arrival_time",
            "children",
        ]
        read_only_fields = ["eta", "status", "actual_arrival_time"]


class TripStopCreateSerializer(serializers.ModelSerializer):
    children = serializers.PrimaryKeyRelatedField(
        queryset=Child.objects.filter(is_active=True), many=True
    )

    class Meta:
        model = TripStop
        fields = ["school", "activity", "sequence_order", "children"]

    def validate(self, attrs):
        if not attrs.get("school") and not attrs.get("activity"):
            raise serializers.ValidationError(
                "A stop needs a school or an activity."
            )
        return attrs


class TripSerializer(serializers.ModelSerializer):
    stops = TripStopSerializer(many=True, read_only=True)
    driver_name = serializers.CharField(source="driver.full_name", read_only=True)

    class Meta:
        model = Trip
        fields = [
            "id",
            "driver",
            "driver_name",
            "carpool_group",
            "date",
            "status",
            "started_at",
            "ended_at",
            "tracking_mode",
            "created_at",
            "stops",
        ]
        read_only_fields = ["driver", "status", "started_at", "ended_at"]


class TripCreateSerializer(serializers.ModelSerializer):
    stops = TripStopCreateSerializer(many=True)

    class Meta:
        model = Trip
        fields = ["carpool_group", "date", "tracking_mode", "stops"]

    def validate_stops(self, stops):
        if not stops:
            raise serializers.ValidationError("A trip needs at least one stop.")
        return stops

    def validate(self, attrs):
        user = self.context["request"].user
        visible = set(
            children_visible_to(user).values_list("id", flat=True)
        )
        for stop in attrs["stops"]:
            for child in stop["children"]:
                if child.id not in visible:
                    raise serializers.ValidationError(
                        f"Child {child.id} is not in your family or carpool groups."
                    )
        return attrs

    def create(self, validated_data):
        stops_data = validated_data.pop("stops")
        trip = Trip.objects.create(
            driver=self.context["request"].user, **validated_data
        )
        for stop_data in stops_data:
            children = stop_data.pop("children")
            stop = TripStop.objects.create(trip=trip, **stop_data)
            TripStopChild.objects.bulk_create(
                [TripStopChild(trip_stop=stop, child=child) for child in children]
            )
        return trip

    def to_representation(self, instance):
        return TripSerializer(instance, context=self.context).data


class TripStopUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            TripStop.Status.EN_ROUTE,
            TripStop.Status.ARRIVED,
            TripStop.Status.PICKED_UP,
            TripStop.Status.SKIPPED,
        ]
    )
    # Optional subset for picked_up; defaults to every child at the stop
    children = serializers.PrimaryKeyRelatedField(
        queryset=Child.objects.all(), many=True, required=False
    )


class LocationPingSerializer(serializers.ModelSerializer):
    recorded_at = serializers.DateTimeField(required=False)

    class Meta:
        model = LocationPing
        fields = ["id", "lat", "lng", "speed", "heading", "recorded_at"]


class PickupEventSerializer(serializers.ModelSerializer):
    child_name = serializers.CharField(source="child.full_name", read_only=True)

    class Meta:
        model = PickupEvent
        fields = [
            "id",
            "child",
            "child_name",
            "date",
            "pickup_method",
            "carpool_assignment",
            "trip_stop_child",
            "status",
            "scheduled_time",
            "created_at",
        ]
        read_only_fields = [
            "child",
            "date",
            "carpool_assignment",
            "trip_stop_child",
            "scheduled_time",
            "created_at",
        ]


class SOSAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = SOSAlert
        fields = [
            "id",
            "trip",
            "raised_by",
            "lat",
            "lng",
            "message",
            "status",
            "created_at",
            "resolved_at",
            "resolved_by",
        ]
        read_only_fields = [
            "raised_by",
            "status",
            "created_at",
            "resolved_at",
            "resolved_by",
        ]


class SOSAlertCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SOSAlert
        fields = ["trip", "lat", "lng", "message"]
        extra_kwargs = {"trip": {"required": True, "allow_null": False}}

    def validate_trip(self, trip):
        # API-DESIGN.md: an SOS is raised from an active trip the user is on.
        request = self.context.get("request")
        from trips.permissions import user_can_access_trip

        if request and not user_can_access_trip(request.user, trip.id):
            raise serializers.ValidationError(
                "You are not a participant on this trip."
            )
        return trip
