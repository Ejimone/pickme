from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/api/v1/health/", permanent=False)),
    path("admin/", admin.site.urls),
    path("api/v1/", include("core.urls")),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/", include("families.urls")),
    path("api/v1/", include("schools.urls")),
    path("api/v1/", include("carpool.urls")),
    path("api/v1/", include("trips.urls")),
    path("api/v1/", include("chat.urls")),
    path("api/v1/", include("notifications.urls")),
]
