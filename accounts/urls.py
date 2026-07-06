from django.urls import path

from accounts.webhooks import ClerkWebhookView

urlpatterns = [
    path("webhooks/clerk/", ClerkWebhookView.as_view(), name="clerk-webhook"),
]
