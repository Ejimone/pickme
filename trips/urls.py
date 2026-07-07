from rest_framework.routers import DefaultRouter

from trips.views import PickupEventViewSet, SOSAlertViewSet, TripViewSet

router = DefaultRouter()
router.register("trips", TripViewSet, basename="trip")
router.register("pickup-events", PickupEventViewSet, basename="pickup-event")
router.register("sos-alerts", SOSAlertViewSet, basename="sos-alert")

urlpatterns = router.urls
