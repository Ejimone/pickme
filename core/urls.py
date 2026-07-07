from django.urls import path

from core.views import MediaSignatureView, health_check

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("media/signature/", MediaSignatureView.as_view(), name="media-signature"),
]
