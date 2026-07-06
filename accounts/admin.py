from django.contrib import admin

from accounts.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "clerk_user_id", "created_at")
    search_fields = ("email", "full_name", "clerk_user_id")
    readonly_fields = ("id", "created_at", "updated_at")
