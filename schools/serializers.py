import zoneinfo

from rest_framework import serializers

from schools.models import School, SchoolCalendarException


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = [
            "id",
            "name",
            "address",
            "lat",
            "lng",
            "timezone",
            "default_dismissal_time",
            "early_dismissal_days",
            "phone",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_timezone(self, value):
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError(f"Unknown IANA timezone: {value}")
        return value

    def validate_early_dismissal_days(self, value):
        if value is None:
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'Expected a mapping of weekday to time, e.g. {"2": "13:30"}.'
            )
        for day, time_str in value.items():
            if not (day.isdigit() and 0 <= int(day) <= 6):
                raise serializers.ValidationError(
                    f"Weekday keys must be '0'–'6' (0=Monday); got {day!r}."
                )
            try:
                hours, minutes = time_str.split(":")
                assert 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59
            except (ValueError, AttributeError, AssertionError):
                raise serializers.ValidationError(
                    f"Times must be 'HH:MM'; got {time_str!r}."
                )
        return value


class SchoolCalendarExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolCalendarException
        fields = ["id", "school", "date", "dismissal_time", "reason", "created_at"]
        read_only_fields = ["id", "school", "created_at"]
