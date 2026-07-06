from rest_framework.routers import DefaultRouter

from chat.views import ChatThreadViewSet

router = DefaultRouter()
router.register("chat-threads", ChatThreadViewSet, basename="chat-thread")

urlpatterns = router.urls
