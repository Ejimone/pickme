from django.contrib import admin

from trips.models import SOSAlert


@admin.register(SOSAlert)
class SOSAlertAdmin(admin.ModelAdmin):
    list_display = ("id", "trip", "raised_by", "status", "created_at", "resolved_at")
    list_filter = ("status",)
    search_fields = ("raised_by__email", "message")
    readonly_fields = ("created_at",)
