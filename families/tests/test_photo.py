"""Child avatar upload (POST /children/{id}/photo/). Uses the fake Cloudinary
backend (default), so nothing hits the network."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

pytestmark = pytest.mark.django_db


def _png(name="ada.png", content_type="image/png", size=None):
    body = b"\x89PNG\r\n\x1a\n fake"
    if size is not None:
        body = b"\x89PNG\r\n\x1a\n" + b"0" * size
    return SimpleUploadedFile(name, body, content_type=content_type)


def _heic():
    return SimpleUploadedFile(
        "IMG_4821.HEIC", b"\x00\x00\x00 ftypheic", content_type="image/heic"
    )


class TestChildPhoto:
    def test_upload_file_sets_photo_url(self, client_a, child_a):
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"file": _png()},
            format="multipart",
        )
        assert resp.status_code == 200
        url = resp.json()["photo_url"]
        assert url and "child_avatars/" in url
        child_a.refresh_from_db()
        assert child_a.photo_url == url

    def test_upload_heic_is_accepted(self, client_a, child_a):
        # The client may send HEIC/HEIF — don't assume JPEG.
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"file": _heic()},
            format="multipart",
        )
        assert resp.status_code == 200
        assert "child_avatars/" in resp.json()["photo_url"]

    def test_accepts_already_hosted_url(self, client_a, child_a):
        hosted = "https://res.cloudinary.com/x/image/upload/child_avatars/ada.png"
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"photo_url": hosted},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["photo_url"] == hosted

    def test_rejects_non_https_photo_url(self, client_a, child_a):
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"photo_url": "http://insecure.example.com/a.png"},
            format="json",
        )
        assert resp.status_code == 400
        assert "photo_url" in resp.json()["error"]["details"]

    def test_missing_file_and_url_400(self, client_a, child_a):
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/", {}, format="json"
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["details"] == {"file": ["No image provided."]}

    def test_unsupported_file_type_400(self, client_a, child_a):
        bad = SimpleUploadedFile(
            "notes.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"file": bad},
            format="multipart",
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["details"] == {
            "file": ["Unsupported file type."]
        }

    def test_oversized_file_400(self, client_a, child_a):
        big = _png(size=10 * 1024 * 1024 + 1)  # just over 10 MB
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"file": big},
            format="multipart",
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["details"] == {
            "file": ["Image is too large (max 10 MB)."]
        }

    def test_cannot_upload_to_another_familys_child(self, client_a, child_b):
        # child_b belongs to family B — invisible to user A → 404, not 403.
        resp = client_a.post(
            f"/api/v1/children/{child_b.id}/photo/",
            {"file": _png()},
            format="multipart",
        )
        assert resp.status_code == 404
