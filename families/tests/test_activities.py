import pytest

from families.models import Activity

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "name": "Soccer practice",
    "day_of_week": 2,
    "start_time": "15:30:00",
    "end_time": "17:00:00",
    "location_name": "West Field",
}


def create_activity(client, child, **overrides):
    return client.post(
        f"/api/v1/children/{child.id}/activities/",
        {**PAYLOAD, **overrides},
        format="json",
    )


class TestActivityCRUD:
    def test_create_and_list(self, client_a, child_a):
        resp = create_activity(client_a, child_a)
        assert resp.status_code == 201
        resp = client_a.get(f"/api/v1/children/{child_a.id}/activities/")
        assert [a["name"] for a in resp.json()["results"]] == ["Soccer practice"]

    def test_update(self, client_a, child_a):
        activity_id = create_activity(client_a, child_a).json()["id"]
        resp = client_a.patch(
            f"/api/v1/activities/{activity_id}/", {"end_time": "17:30:00"}
        )
        assert resp.status_code == 200
        assert resp.json()["end_time"] == "17:30:00"

    def test_delete(self, client_a, child_a):
        activity_id = create_activity(client_a, child_a).json()["id"]
        assert (
            client_a.delete(f"/api/v1/activities/{activity_id}/").status_code
            == 204
        )
        assert not Activity.objects.filter(pk=activity_id).exists()

    def test_end_before_start_rejected(self, client_a, child_a):
        resp = create_activity(client_a, child_a, end_time="15:00:00")
        assert resp.status_code == 400

    def test_patch_cannot_invert_times(self, client_a, child_a):
        activity_id = create_activity(client_a, child_a).json()["id"]
        resp = client_a.patch(
            f"/api/v1/activities/{activity_id}/", {"end_time": "15:00:00"}
        )
        assert resp.status_code == 400


class TestActivityScoping:
    def test_cannot_create_for_other_family_child(self, client_a, child_b):
        resp = create_activity(client_a, child_b)
        assert resp.status_code == 404

    def test_cannot_list_other_family_activities(self, client_a, client_b, child_b):
        create_activity(client_b, child_b)
        resp = client_a.get(f"/api/v1/children/{child_b.id}/activities/")
        assert resp.status_code == 404

    def test_cannot_update_other_family_activity(self, client_a, client_b, child_b):
        activity_id = create_activity(client_b, child_b).json()["id"]
        resp = client_a.patch(
            f"/api/v1/activities/{activity_id}/", {"name": "Hijacked"}
        )
        assert resp.status_code == 404
