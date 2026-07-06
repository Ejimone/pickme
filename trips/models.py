import uuid

from django.conf import settings
from django.db import models


class Trip(models.Model):
    """A driver's real-time run for a day; may cover multiple stops/kids."""

    class Status(models.TextChoices):
        NOT_STARTED = "not_started"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    class TrackingMode(models.TextChoices):
        LIVE_GPS = "live_gps"
        STATUS_ONLY = "status_only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trips"
    )
    carpool_group = models.ForeignKey(
        "carpool.CarpoolGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,  # null = solo parent pickup, not a carpool run
        related_name="trips",
    )
    date = models.DateField()
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.NOT_STARTED
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    tracking_mode = models.CharField(
        max_length=15, choices=TrackingMode.choices, default=TrackingMode.LIVE_GPS
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trips"

    def __str__(self):
        return f"Trip {self.date} by {self.driver} ({self.status})"


class TripStop(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        EN_ROUTE = "en_route"
        ARRIVED = "arrived"
        PICKED_UP = "picked_up"
        SKIPPED = "skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="stops")
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        null=True,
        blank=True,  # nullable to support activity pickups
        related_name="trip_stops",
    )
    activity = models.ForeignKey(
        "families.Activity",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="trip_stops",
    )
    sequence_order = models.IntegerField()
    eta = models.DateTimeField(null=True, blank=True)  # recalculated periodically
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    actual_arrival_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "trip_stops"
        ordering = ["sequence_order"]

    def __str__(self):
        return f"Stop #{self.sequence_order} of {self.trip_id} ({self.status})"


class TripStopChild(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip_stop = models.ForeignKey(
        TripStop, on_delete=models.CASCADE, related_name="children"
    )
    child = models.ForeignKey(
        "families.Child", on_delete=models.CASCADE, related_name="trip_stop_entries"
    )
    picked_up_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "trip_stop_children"
        constraints = [
            models.UniqueConstraint(
                fields=["trip_stop", "child"], name="unique_stop_child"
            )
        ]

    def __str__(self):
        return f"{self.child} at {self.trip_stop_id}"


class LocationPing(models.Model):
    """High-volume, short-retention (purged nightly beyond ~30 days)."""

    id = models.BigAutoField(primary_key=True)  # UUID overkill at this volume
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="pings")
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    speed = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "location_pings"
        indexes = [
            # Write-heavy table queried by "latest ping for trip"
            models.Index(fields=["trip", "recorded_at"], name="ping_trip_recorded_idx")
        ]

    def __str__(self):
        return f"Ping {self.trip_id} @ {self.recorded_at}"
