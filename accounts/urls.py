from django.urls import path

from accounts.views import MeView
from accounts.webhooks import ClerkWebhookView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("webhooks/clerk/", ClerkWebhookView.as_view(), name="clerk-webhook"),
]
