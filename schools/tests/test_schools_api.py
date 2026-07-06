import pytest

from schools.models import SchoolCalendarException

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(db):
    from rest_framework.test import APIClient

    from accounts.models import User

    user = User.objects.create_user(
        email="s@example.com", clerk_user_id="user_s"
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


SCHOOL_PAYLOAD = {
    "name": "Washington Middle",
    "address": "42 Oak Ave",
    "timezone": "America/Chicago",
    "default_dismissal_time": "15:30:00",
}


class TestSchools:
    def test_create_and_search(self, client):
        assert (
            client.post("/api/v1/schools/", SCHOOL_PAYLOAD).status_code == 201
        )
        resp = client.get("/api/v1/schools/?search=washington")
        assert len(resp.json()["results"]) == 1

    def test_invalid_timezone_rejected(self, client):
        resp = client.post(
            "/api/v1/schools/", {**SCHOOL_PAYLOAD, "timezone": "Mars/Olympus"}
        )
        assert resp.status_code == 400

    def test_invalid_early_dismissal_days_rejected(self, client):
        for bad in [["2"], {"7": "13:30"}, {"2": "25:00"}]:
            resp = client.post(
                "/api/v1/schools/",
                {**SCHOOL_PAYLOAD, "early_dismissal_days": bad},
                format="json",
            )
            assert resp.status_code == 400, bad


class TestCalendarExceptions:
    def _create_school(self, client):
        return client.post("/api/v1/schools/", SCHOOL_PAYLOAD).json()["id"]

    def test_create_and_filter(self, client):
        school_id = self._create_school(client)
        url = f"/api/v1/schools/{school_id}/calendar-exceptions/"
        assert (
            client.post(
                url,
                {"date": "2026-09-07", "dismissal_time": None, "reason": "Labor Day"},
                format="json",
            ).status_code
            == 201
        )
        assert (
            client.post(
                url, {"date": "2026-09-18", "dismissal_time": "13:00:00", "reason": "PD day"}
            ).status_code
            == 201
        )

        resp = client.get(f"{url}?from=2026-09-10&to=2026-09-30")
        results = resp.json()["results"]
        assert [r["reason"] for r in results] == ["PD day"]

    def test_duplicate_date_rejected(self, client):
        school_id = self._create_school(client)
        url = f"/api/v1/schools/{school_id}/calendar-exceptions/"
        payload = {"date": "2026-09-07", "reason": "Holiday"}
        assert client.post(url, payload).status_code == 201
        assert client.post(url, payload).status_code == 400
