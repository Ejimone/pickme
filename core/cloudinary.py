"""Cloudinary media integration — backend-selectable like the Maps/Expo clients.

`CLOUDINARY_BACKEND` picks the implementation ("fake" | "cloudinary"), so tests
and local dev never hit Cloudinary. Two operations:

- `upload(file, folder)` — server-side signed upload (used by the child-avatar
  proxy endpoint, which stores the returned secure URL).
- `signed_params(folder, resource_type)` — hands a short-lived signature back to
  the client so it can upload directly to Cloudinary (used for chat
  attachments). The API secret never leaves the server.

Both are implemented with `requests` + `hashlib` (Cloudinary's documented
signed-upload REST contract), so there's no extra Python dependency.
"""

import hashlib
import time

import requests
from django.conf import settings

UPLOAD_URL = "https://api.cloudinary.com/v1_1/{cloud}/{resource}/upload"


def _signature(params, api_secret):
    """Cloudinary signature: SHA-1 of the sorted `k=v&...` params + api_secret."""
    payload = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha1(f"{payload}{api_secret}".encode()).hexdigest()


class FakeCloudinaryService:
    """Deterministic, network-free stand-in for tests/local dev."""

    backend = "fake"

    def signed_params(self, folder=None, resource_type="image"):
        folder = folder or settings.CLOUDINARY_UPLOAD_FOLDER
        timestamp = int(time.time())
        cloud = settings.CLOUDINARY_CLOUD_NAME or "demo"
        return {
            "cloud_name": cloud,
            "api_key": settings.CLOUDINARY_API_KEY or "fake-key",
            "timestamp": timestamp,
            "folder": folder,
            "signature": "fake-signature",
            "resource_type": resource_type,
            "upload_url": UPLOAD_URL.format(cloud=cloud, resource=resource_type),
        }

    def upload(self, file, folder=None):
        folder = folder or settings.CLOUDINARY_UPLOAD_FOLDER
        name = getattr(file, "name", "upload")
        return f"https://res.cloudinary.com/demo/image/upload/{folder}/{name}"


class CloudinaryService:
    backend = "cloudinary"

    def signed_params(self, folder=None, resource_type="image"):
        folder = folder or settings.CLOUDINARY_UPLOAD_FOLDER
        timestamp = int(time.time())
        signature = _signature(
            {"folder": folder, "timestamp": timestamp},
            settings.CLOUDINARY_API_SECRET,
        )
        return {
            "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
            "api_key": settings.CLOUDINARY_API_KEY,
            "timestamp": timestamp,
            "folder": folder,
            "signature": signature,
            "resource_type": resource_type,
            "upload_url": UPLOAD_URL.format(
                cloud=settings.CLOUDINARY_CLOUD_NAME, resource=resource_type
            ),
        }

    def upload(self, file, folder=None):
        folder = folder or settings.CLOUDINARY_UPLOAD_FOLDER
        timestamp = int(time.time())
        params = {"folder": folder, "timestamp": timestamp}
        params["signature"] = _signature(params, settings.CLOUDINARY_API_SECRET)
        params["api_key"] = settings.CLOUDINARY_API_KEY
        response = requests.post(
            UPLOAD_URL.format(
                cloud=settings.CLOUDINARY_CLOUD_NAME, resource="image"
            ),
            data=params,
            files={"file": file},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["secure_url"]


def get_media_client():
    if settings.CLOUDINARY_BACKEND == "cloudinary":
        return CloudinaryService()
    return FakeCloudinaryService()
