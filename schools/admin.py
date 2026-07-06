from django.contrib import admin

from schools.models import School, SchoolCalendarException


class SchoolCalendarExceptionInline(admin.TabularInline):
    model = SchoolCalendarException
    extra = 0


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "timezone", "default_dismissal_time")
    search_fields = ("name", "address")
    inlines = [SchoolCalendarExceptionInline]
