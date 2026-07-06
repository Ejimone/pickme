from django.contrib import admin

from notifications.models import DeviceToken, Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("type", "user", "title", "is_read", "delivered_at", "created_at")
    list_filter = ("type", "is_read")
    search_fields = ("title", "body", "user__email")
    readonly_fields = ("created_at",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "notification_type",
        "push_enabled",
        "sms_enabled",
        "email_enabled",
    )
    list_filter = ("notification_type", "push_enabled")


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "token", "created_at")
    list_filter = ("platform",)
    search_fields = ("token", "user__email")
