from rest_framework.routers import DefaultRouter

from carpool.views import (
    AssignmentViewSet,
    CarpoolGroupViewSet,
    SwapRequestViewSet,
)

router = DefaultRouter()
router.register("carpool-groups", CarpoolGroupViewSet, basename="carpool-group")
router.register("assignments", AssignmentViewSet, basename="assignment")
router.register("swap-requests", SwapRequestViewSet, basename="swap-request")

urlpatterns = router.urls
