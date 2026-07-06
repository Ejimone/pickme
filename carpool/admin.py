from django.contrib import admin

from carpool.models import (
    CarpoolAssignment,
    CarpoolGroup,
    CarpoolGroupMember,
    CarpoolRotationOrder,
    CarpoolRotationRule,
    CarpoolSwapRequest,
)


class CarpoolGroupMemberInline(admin.TabularInline):
    model = CarpoolGroupMember
    extra = 0


@admin.register(CarpoolGroup)
class CarpoolGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "invite_code", "created_at")
    search_fields = ("name",)
    inlines = [CarpoolGroupMemberInline]


class RotationOrderInline(admin.TabularInline):
    model = CarpoolRotationOrder
    extra = 0


@admin.register(CarpoolRotationRule)
class RotationRuleAdmin(admin.ModelAdmin):
    list_display = ("carpool_group", "rotation_type", "start_date")
    inlines = [RotationOrderInline]


@admin.register(CarpoolAssignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("carpool_group", "date", "driver_family", "status")
    list_filter = ("status", "is_auto_suggested")
    date_hierarchy = "date"


@admin.register(CarpoolSwapRequest)
class SwapRequestAdmin(admin.ModelAdmin):
    list_display = ("assignment", "target_family", "status", "created_at")
    list_filter = ("status",)
