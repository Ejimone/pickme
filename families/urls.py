from django.urls import path
from rest_framework.routers import DefaultRouter

from families.views import ChildViewSet, FamilyViewSet, InviteAcceptView

router = DefaultRouter()
router.register("families", FamilyViewSet, basename="family")
router.register("children", ChildViewSet, basename="child")

urlpatterns = [
    path(
        "family-invites/accept/",
        InviteAcceptView.as_view(),
        name="family-invite-accept",
    ),
    *router.urls,
]
