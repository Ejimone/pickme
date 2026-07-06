import uuid

from django.db import models


class School(models.Model):
    """Shared reference data — not family-scoped."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=512)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")  # IANA tz name
    default_dismissal_time = models.TimeField()
    # Weekday overrides for regular early days, e.g. {"2": "13:30"} =
    # every Wednesday dismisses at 1:30pm. Keys are Python weekday ints
    # (0=Monday) as strings, values "HH:MM". See DECISIONS.md.
    early_dismissal_days = models.JSONField(null=True, blank=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "schools"

    def __str__(self):
        return self.name


class SchoolCalendarException(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="calendar_exceptions"
    )
    date = models.DateField()
    # null = no school that day (holiday, snow day)
    dismissal_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "school_calendar_exceptions"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "date"], name="unique_school_date"
            )
        ]

    def __str__(self):
        return f"{self.school} {self.date}: {self.reason}"
