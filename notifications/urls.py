from rest_framework.routers import DefaultRouter

from notifications.views import (
    DeviceTokenViewSet,
    NotificationPreferenceViewSet,
    NotificationViewSet,
)

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")
router.register(
    "notification-preferences",
    NotificationPreferenceViewSet,
    basename="notification-preference",
)
router.register("device-tokens", DeviceTokenViewSet, basename="device-token")

urlpatterns = router.urls
