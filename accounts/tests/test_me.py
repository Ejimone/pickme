import pytest
from rest_framework.test import APIClient

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_me_returns_current_user_summary():
    user = User.objects.create_user(
        email="sarah@example.com",
        clerk_user_id="user_me1",
        full_name="Sarah Ortiz",
        avatar_url="https://img.example/sarah.png",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    resp = client.get("/api/v1/me/")
    assert resp.status_code == 200
    assert resp.json() == {
        "id": str(user.id),
        "full_name": "Sarah Ortiz",
        "email": "sarah@example.com",
        "avatar_url": "https://img.example/sarah.png",
    }


def test_me_requires_auth():
    resp = APIClient().get("/api/v1/me/")
    assert resp.status_code == 401
