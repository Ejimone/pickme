from django.urls import path
from rest_framework.routers import DefaultRouter

from carpool.views import (
    AssignmentViewSet,
    CarpoolGroupViewSet,
    CarpoolInviteAcceptView,
    SwapRequestViewSet,
)

router = DefaultRouter()
router.register("carpool-groups", CarpoolGroupViewSet, basename="carpool-group")
router.register("assignments", AssignmentViewSet, basename="assignment")
router.register("swap-requests", SwapRequestViewSet, basename="swap-request")

urlpatterns = [
    path(
        "carpool-group-invites/accept/",
        CarpoolInviteAcceptView.as_view(),
        name="carpool-invite-accept",
    ),
    *router.urls,
]
