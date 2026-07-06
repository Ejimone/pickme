from rest_framework import serializers

from notifications.models import DeviceToken, Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "data",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "notification_type",
            "push_enabled",
            "sms_enabled",
            "email_enabled",
        ]
        read_only_fields = ["id", "notification_type"]


class DeviceTokenSerializer(serializers.ModelSerializer):
    # Drop the model's UniqueValidator so re-registering an existing token
    # rebinds it (handled by update_or_create in the view) instead of 400-ing.
    token = serializers.CharField(max_length=255, validators=[])

    class Meta:
        model = DeviceToken
        fields = ["id", "token", "platform", "created_at"]
        read_only_fields = ["id", "created_at"]
