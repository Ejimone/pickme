from django.contrib import admin

from families.models import Child, Family, FamilyInvite, FamilyMember


class FamilyMemberInline(admin.TabularInline):
    model = FamilyMember
    extra = 0


@admin.register(Family)
class FamilyAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    search_fields = ("name",)
    inlines = [FamilyMemberInline]


@admin.register(FamilyInvite)
class FamilyInviteAdmin(admin.ModelAdmin):
    list_display = ("email", "family", "status", "created_at")
    list_filter = ("status",)


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = ("full_name", "family", "school", "grade", "is_active")
    list_filter = ("is_active",)
    search_fields = ("full_name",)
