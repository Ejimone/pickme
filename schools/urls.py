from rest_framework.routers import DefaultRouter

from schools.views import SchoolViewSet

router = DefaultRouter()
router.register("schools", SchoolViewSet, basename="school")

urlpatterns = router.urls
