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


def test_cloudinary_upload_signs_all_options_and_returns_secure_url(
    settings, mocker
):
    """The avatar proxy passes transformation/format/overwrite options; every
    signed form field except file/api_key/resource_type/signature must be part
    of the signature, or Cloudinary rejects the upload."""
    from core import cloudinary as cl

    settings.CLOUDINARY_CLOUD_NAME = "demo"
    settings.CLOUDINARY_API_KEY = "123"
    settings.CLOUDINARY_API_SECRET = "s3cr3t"

    post = mocker.patch.object(cl.requests, "post")
    post.return_value.json.return_value = {
        "secure_url": "https://res.cloudinary.com/demo/image/upload/child_avatars/x.jpg"
    }
    post.return_value.raise_for_status.return_value = None

    url = cl.CloudinaryService().upload(
        object(),
        folder="child_avatars",
        resource_type="image",
        overwrite=True,
        transformation="c_fill,g_face,h_512,w_512,q_auto",
        format="jpg",
    )

    assert url.endswith("child_avatars/x.jpg")
    # resource_type is the URL path segment, not a signed field.
    assert post.call_args.args[0] == (
        "https://api.cloudinary.com/v1_1/demo/image/upload"
    )
    sent = post.call_args.kwargs["data"]
    assert "resource_type" not in sent
    signed = {
        k: v for k, v in sent.items() if k not in ("signature", "api_key")
    }
    payload = "&".join(f"{k}={signed[k]}" for k in sorted(signed))
    expected = hashlib.sha1(f"{payload}s3cr3t".encode()).hexdigest()
    assert sent["signature"] == expected


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
