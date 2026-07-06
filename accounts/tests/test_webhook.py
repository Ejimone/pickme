import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from rest_framework.test import APIClient

from accounts.models import User

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/v1/webhooks/clerk/"


def sign_payload(secret, payload: bytes):
    """Produce valid Svix signature headers for a payload."""
    msg_id = f"msg_{uuid.uuid4().hex}"
    timestamp = str(int(time.time()))
    secret_bytes = base64.b64decode(secret.removeprefix("whsec_"))
    to_sign = f"{msg_id}.{timestamp}.".encode() + payload
    signature = base64.b64encode(
        hmac.new(secret_bytes, to_sign, hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": msg_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{signature}",
    }


def clerk_user_payload(event_type, clerk_id="user_wh1", email="wh@example.com"):
    return {
        "type": event_type,
        "data": {
            "id": clerk_id,
            "first_name": "Pat",
            "last_name": "Ortiz",
            "image_url": "https://img.clerk.com/abc",
            "primary_email_address_id": "idn_1",
            "email_addresses": [{"id": "idn_1", "email_address": email}],
            "phone_numbers": [{"phone_number": "+15551234567"}],
        },
    }


@pytest.fixture
def client():
    return APIClient()


def post_event(client, settings, event, valid_sig=True):
    body = json.dumps(event).encode()
    headers = sign_payload(settings.CLERK_WEBHOOK_SIGNING_SECRET, body)
    if not valid_sig:
        headers["svix-signature"] = "v1,invalidsignature"
    return client.generic(
        "POST",
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        **{f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()},
    )


class TestClerkWebhook:
    def test_user_created(self, client, clerk_settings):
        resp = post_event(
            client, clerk_settings, clerk_user_payload("user.created")
        )
        assert resp.status_code == 204
        user = User.objects.get(clerk_user_id="user_wh1")
        assert user.email == "wh@example.com"
        assert user.full_name == "Pat Ortiz"
        assert user.phone == "+15551234567"

    def test_user_updated_syncs_existing(self, client, clerk_settings):
        User.objects.create_user(
            email="user_wh1@pending.clerk.local", clerk_user_id="user_wh1"
        )
        resp = post_event(
            client,
            clerk_settings,
            clerk_user_payload("user.updated", email="real@example.com"),
        )
        assert resp.status_code == 204
        user = User.objects.get(clerk_user_id="user_wh1")
        assert user.email == "real@example.com"
        assert User.objects.count() == 1

    def test_user_deleted_deactivates(self, client, clerk_settings):
        User.objects.create_user(email="x@example.com", clerk_user_id="user_wh1")
        resp = post_event(
            client,
            clerk_settings,
            {"type": "user.deleted", "data": {"id": "user_wh1", "deleted": True}},
        )
        assert resp.status_code == 204
        user = User.objects.get(clerk_user_id="user_wh1")
        assert user.is_active is False

    def test_invalid_signature_rejected(self, client, clerk_settings):
        resp = post_event(
            client,
            clerk_settings,
            clerk_user_payload("user.created"),
            valid_sig=False,
        )
        assert resp.status_code == 400
        assert not User.objects.exists()

    def test_unknown_event_acknowledged(self, client, clerk_settings):
        resp = post_event(
            client,
            clerk_settings,
            {"type": "session.created", "data": {"id": "sess_1"}},
        )
        assert resp.status_code == 204
