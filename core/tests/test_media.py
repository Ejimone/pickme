"""Cloudinary signed-upload params endpoint (POST /media/signature/)."""

import hashlib

import pytest
from rest_framework.test import APIClient

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_cloudinary_signature_covers_folder_and_timestamp(settings):
    """The real backend must sign exactly {folder, timestamp} so a client
    upload of {file, api_key, timestamp, signature, folder} verifies."""
    from core.cloudinary import CloudinaryService

    settings.CLOUDINARY_CLOUD_NAME = "demo"
    settings.CLOUDINARY_API_KEY = "123"
    settings.CLOUDINARY_API_SECRET = "s3cr3t"
    params = CloudinaryService().signed_params(folder="chat")

    expected = hashlib.sha1(
        f"folder={params['folder']}&timestamp={params['timestamp']}s3cr3t".encode()
    ).hexdigest()
    assert params["signature"] == expected
    assert params["upload_url"] == (
        "https://api.cloudinary.com/v1_1/demo/image/upload"
    )


@pytest.fixture
def client(db):
    user = User.objects.create_user(email="m@example.com", clerk_user_id="user_m")
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestMediaSignature:
    def test_requires_auth(self):
        resp = APIClient().post("/api/v1/media/signature/")
        assert resp.status_code in (401, 403)

    def test_returns_signed_params(self, client):
        resp = client.post(
            "/api/v1/media/signature/", {"folder": "chat"}, format="json"
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in ("cloud_name", "api_key", "timestamp", "signature", "upload_url"):
            assert key in body
        assert body["folder"] == "chat"

    def test_defaults_folder(self, client, settings):
        settings.CLOUDINARY_UPLOAD_FOLDER = "pickme"
        resp = client.post("/api/v1/media/signature/", {}, format="json")
        assert resp.status_code == 200
        assert resp.json()["folder"] == "pickme"
