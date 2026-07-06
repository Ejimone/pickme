"""Stage 1's required tests: user A must never see or touch family B's data."""

import pytest

from families.models import Child

pytestmark = pytest.mark.django_db


class TestFamilyScoping:
    def test_list_only_own_families(self, client_a, family_a, family_b):
        resp = client_a.get("/api/v1/families/")
        ids = [f["id"] for f in resp.json()["results"]]
        assert ids == [str(family_a.id)]

    def test_cannot_retrieve_other_family(self, client_a, family_b):
        resp = client_a.get(f"/api/v1/families/{family_b.id}/")
        assert resp.status_code == 404

    def test_cannot_rename_other_family(self, client_a, family_b):
        resp = client_a.patch(
            f"/api/v1/families/{family_b.id}/", {"name": "Hijacked"}
        )
        assert resp.status_code == 404
        family_b.refresh_from_db()
        assert family_b.name == "Family B"

    def test_cannot_list_other_family_members(self, client_a, family_b):
        resp = client_a.get(f"/api/v1/families/{family_b.id}/members/")
        assert resp.status_code == 404


class TestChildScoping:
    def test_list_only_own_children(self, client_a, child_a, child_b):
        resp = client_a.get("/api/v1/children/")
        names = [c["full_name"] for c in resp.json()["results"]]
        assert names == ["Ada A"]

    def test_cannot_retrieve_other_family_child(self, client_a, child_b):
        resp = client_a.get(f"/api/v1/children/{child_b.id}/")
        assert resp.status_code == 404

    def test_cannot_update_other_family_child(self, client_a, child_b):
        resp = client_a.patch(
            f"/api/v1/children/{child_b.id}/", {"full_name": "Hijacked"}
        )
        assert resp.status_code == 404

    def test_cannot_create_child_in_other_family(
        self, client_a, family_b, school
    ):
        resp = client_a.post(
            "/api/v1/children/",
            {"family": str(family_b.id), "full_name": "Sneaky"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "validation_error"
        assert not Child.objects.filter(full_name="Sneaky").exists()

    def test_soft_delete(self, client_a, child_a):
        resp = client_a.delete(f"/api/v1/children/{child_a.id}/")
        assert resp.status_code == 204
        child_a.refresh_from_db()
        assert child_a.is_active is False
        # gone from the API…
        assert client_a.get(f"/api/v1/children/{child_a.id}/").status_code == 404

    def test_filter_by_family(self, client_a, user_b, child_a, family_b):
        # user_a joins family_b too, then filters
        from families.models import FamilyMember

        FamilyMember.objects.create(family=family_b, user=client_a.handler._force_user)
        resp = client_a.get(f"/api/v1/children/?family={family_b.id}")
        assert resp.json()["results"] == []


class TestFamilyCreation:
    def test_creator_becomes_owner(self, client_a, user_a):
        resp = client_a.post("/api/v1/families/", {"name": "New Family"})
        assert resp.status_code == 201
        family_id = resp.json()["id"]
        members = client_a.get(f"/api/v1/families/{family_id}/members/").json()
        assert members["results"][0]["role"] == "owner"
        assert members["results"][0]["user"]["id"] == str(user_a.id)

    def test_anonymous_rejected(self, db):
        from rest_framework.test import APIClient

        resp = APIClient().get("/api/v1/families/")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "not_authenticated"
