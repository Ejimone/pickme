"""Clerk webhook receiver (`/api/v1/webhooks/clerk/`).

Primary sync path for the local `users` table. Authenticated by Svix
signature verification, not a user JWT.
"""

import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from svix.webhooks import Webhook, WebhookVerificationError

from accounts.models import User

logger = logging.getLogger(__name__)


def _primary_email(data):
    """Pull the primary email address out of a Clerk user payload."""
    addresses = data.get("email_addresses") or []
    primary_id = data.get("primary_email_address_id")
    for entry in addresses:
        if entry.get("id") == primary_id:
            return entry.get("email_address")
    if addresses:
        return addresses[0].get("email_address")
    return None


def _full_name(data):
    return " ".join(
        part for part in [data.get("first_name"), data.get("last_name")] if part
    )


@method_decorator(csrf_exempt, name="dispatch")
class ClerkWebhookView(View):
    def post(self, request):
        secret = settings.CLERK_WEBHOOK_SIGNING_SECRET
        if not secret:
            logger.error("CLERK_WEBHOOK_SIGNING_SECRET is not configured")
            return JsonResponse(
                {"error": {"code": "server_error", "message": "Webhook not configured", "details": {}}},
                status=500,
            )
        try:
            event = Webhook(secret).verify(request.body, dict(request.headers))
        except WebhookVerificationError:
            return JsonResponse(
                {"error": {"code": "invalid_signature", "message": "Invalid webhook signature", "details": {}}},
                status=400,
            )

        event_type = event.get("type", "")
        data = event.get("data", {})
        clerk_user_id = data.get("id")
        if not clerk_user_id:
            return HttpResponse(status=204)

        if event_type in ("user.created", "user.updated"):
            self.upsert_user(clerk_user_id, data)
        elif event_type == "user.deleted":
            User.objects.filter(clerk_user_id=clerk_user_id).delete()
        # Unknown event types are acknowledged so Clerk stops retrying.
        return HttpResponse(status=204)

    @staticmethod
    def upsert_user(clerk_user_id, data):
        fields = {
            "full_name": _full_name(data),
            "phone": (data.get("phone_numbers") or [{}])[0].get("phone_number"),
            "avatar_url": data.get("image_url"),
        }
        email = _primary_email(data)
        if email:
            fields["email"] = email
        user, created = User.objects.update_or_create(
            clerk_user_id=clerk_user_id, defaults=fields
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
