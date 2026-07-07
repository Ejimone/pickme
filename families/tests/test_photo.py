"""Child avatar upload (POST /children/{id}/photo/). Uses the fake Cloudinary
backend (default), so nothing hits the network."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

pytestmark = pytest.mark.django_db


def _png():
    return SimpleUploadedFile("ada.png", b"\x89PNG\r\n\x1a\n fake", content_type="image/png")


class TestChildPhoto:
    def test_upload_file_sets_photo_url(self, client_a, child_a):
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"file": _png()},
            format="multipart",
        )
        assert resp.status_code == 200
        url = resp.json()["photo_url"]
        assert url and "children/" in url
        child_a.refresh_from_db()
        assert child_a.photo_url == url

    def test_accepts_already_hosted_url(self, client_a, child_a):
        hosted = "https://res.cloudinary.com/x/image/upload/children/ada.png"
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/",
            {"photo_url": hosted},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["photo_url"] == hosted

    def test_missing_file_and_url_400(self, client_a, child_a):
        resp = client_a.post(
            f"/api/v1/children/{child_a.id}/photo/", {}, format="json"
        )
        assert resp.status_code == 400

    def test_cannot_upload_to_another_familys_child(self, client_a, child_b):
        # child_b belongs to family B — invisible to user A → 404, not 403.
        resp = client_a.post(
            f"/api/v1/children/{child_b.id}/photo/",
            {"file": _png()},
            format="multipart",
        )
        assert resp.status_code == 404
