import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_health_check_is_public():
    resp = APIClient().get("/api/v1/health/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
