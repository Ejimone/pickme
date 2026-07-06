from rest_framework.routers import DefaultRouter

from trips.views import PickupEventViewSet, TripViewSet

router = DefaultRouter()
router.register("trips", TripViewSet, basename="trip")
router.register("pickup-events", PickupEventViewSet, basename="pickup-event")

urlpatterns = router.urls
