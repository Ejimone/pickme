"""Carpool group CRUD, join-by-code, rotation rule endpoint, scoping."""

import datetime

import pytest

from carpool.models import CarpoolAssignment, CarpoolGroup
from carpool.tests.conftest import make_rule

pytestmark = pytest.mark.django_db

MON = datetime.date(2026, 7, 6)


class TestGroupCRUD:
    def test_create_makes_family_admin(self, clients, actors, school):
        _, families = actors
        resp = clients["a"].post(
            "/api/v1/carpool-groups/",
            {
                "school": str(school.id),
                "name": "New Crew",
                "family": str(families["a"].id),
            },
        )
        assert resp.status_code == 201
        group = CarpoolGroup.objects.get(pk=resp.json()["id"])
        member = group.members.get()
        assert member.family == families["a"]
        assert member.role == "admin"
        assert resp.json()["invite_code"]

    def test_cannot_create_for_other_family(self, clients, actors, school):
        _, families = actors
        resp = clients["a"].post(
            "/api/v1/carpool-groups/",
            {
                "school": str(school.id),
                "name": "Sneaky",
                "family": str(families["b"].id),
            },
        )
        assert resp.status_code == 400

    def test_list_scoped_to_memberships(self, clients, group):
        assert [g["id"] for g in clients["a"].get("/api/v1/carpool-groups/").json()["results"]] == [str(group.id)]
        assert clients["d"].get("/api/v1/carpool-groups/").json()["results"] == []

    def test_outsider_cannot_retrieve(self, clients, group):
        resp = clients["d"].get(f"/api/v1/carpool-groups/{group.id}/")
        assert resp.status_code == 404

    def test_join_by_invite_code(self, clients, actors, group):
        _, families = actors
        resp = clients["d"].post(
            "/api/v1/carpool-groups/join/",
            {"invite_code": group.invite_code, "family": str(families["d"].id)},
        )
        assert resp.status_code == 201
        assert group.members.filter(family=families["d"], role="member").exists()
        # idempotent
        resp = clients["d"].post(
            "/api/v1/carpool-groups/join/",
            {"invite_code": group.invite_code, "family": str(families["d"].id)},
        )
        assert resp.status_code == 200

    def test_bad_invite_code(self, clients, actors):
        _, families = actors
        resp = clients["d"].post(
            "/api/v1/carpool-groups/join/",
            {"invite_code": "NOPE1234", "family": str(families["d"].id)},
        )
        assert resp.status_code == 404

    def test_admin_removes_member(self, clients, actors, group):
        _, families = actors
        member = group.members.get(family=families["b"])
        resp = clients["a"].delete(
            f"/api/v1/carpool-groups/{group.id}/members/{member.id}/"
        )
        assert resp.status_code == 204

    def test_member_cannot_remove(self, clients, actors, group):
        _, families = actors
        member = group.members.get(family=families["c"])
        resp = clients["b"].delete(
            f"/api/v1/carpool-groups/{group.id}/members/{member.id}/"
        )
        assert resp.status_code == 403

    def test_cannot_remove_only_admin(self, clients, actors, group):
        _, families = actors
        admin_row = group.members.get(family=families["a"])
        resp = clients["a"].delete(
            f"/api/v1/carpool-groups/{group.id}/members/{admin_row.id}/"
        )
        assert resp.status_code == 400


class TestRotationRuleEndpoint:
    def _rule_payload(self, families):
        return {
            "rotation_type": "weighted",
            "cycle_days": [0, 1, 2, 3, 4],
            "start_date": "2026-07-06",
            "order": [
                {"family": str(families["a"].id), "position": 0, "weight": 2},
                {"family": str(families["b"].id), "position": 1, "weight": 1},
            ],
        }

    def test_admin_puts_rule(self, clients, actors, group):
        _, families = actors
        resp = clients["a"].put(
            f"/api/v1/carpool-groups/{group.id}/rotation-rule/",
            self._rule_payload(families),
            format="json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["rotation_type"] == "weighted"
        assert len(body["order"]) == 2

        # replace = PUT again with different order
        payload = self._rule_payload(families)
        payload["order"] = [
            {"family": str(families["c"].id), "position": 0, "weight": 1}
        ]
        resp = clients["a"].put(
            f"/api/v1/carpool-groups/{group.id}/rotation-rule/",
            payload,
            format="json",
        )
        assert resp.status_code == 200
        assert len(resp.json()["order"]) == 1

    def test_member_cannot_put_rule(self, clients, actors, group):
        _, families = actors
        resp = clients["b"].put(
            f"/api/v1/carpool-groups/{group.id}/rotation-rule/",
            self._rule_payload(families),
            format="json",
        )
        assert resp.status_code == 403

    def test_order_must_be_group_members(self, clients, actors, group):
        _, families = actors
        payload = self._rule_payload(families)
        payload["order"].append(
            {"family": str(families["d"].id), "position": 2, "weight": 1}
        )
        resp = clients["a"].put(
            f"/api/v1/carpool-groups/{group.id}/rotation-rule/",
            payload,
            format="json",
        )
        assert resp.status_code == 400

    def test_get_missing_rule_404(self, clients, group):
        resp = clients["a"].get(
            f"/api/v1/carpool-groups/{group.id}/rotation-rule/"
        )
        assert resp.status_code == 404


class TestGenerateEndpoint:
    def test_generate_and_list(self, clients, actors, group):
        _, families = actors
        make_rule(group, [families["a"], families["b"], families["c"]])
        resp = clients["a"].post(
            f"/api/v1/carpool-groups/{group.id}/assignments/generate/",
            {"from": "2026-07-06", "to": "2026-07-10"},
        )
        assert resp.status_code == 201
        created = resp.json()["created"]
        assert len(created) == 5
        assert created[0]["driver_family_name"] == "Family A"
        assert created[0]["status"] == "suggested"

        resp = clients["a"].get(
            f"/api/v1/carpool-groups/{group.id}/assignments/?from=2026-07-06&to=2026-07-07"
        )
        assert len(resp.json()["results"]) == 2

    def test_generate_without_rule_400(self, clients, group):
        resp = clients["a"].post(
            f"/api/v1/carpool-groups/{group.id}/assignments/generate/",
            {"from": "2026-07-06", "to": "2026-07-10"},
        )
        assert resp.status_code == 400

    def test_outsider_cannot_generate(self, clients, actors, group):
        _, families = actors
        make_rule(group, [families["a"]])
        resp = clients["d"].post(
            f"/api/v1/carpool-groups/{group.id}/assignments/generate/",
            {"from": "2026-07-06", "to": "2026-07-10"},
        )
        assert resp.status_code == 404


class TestAssignmentPatch:
    def test_member_reassigns_driver(self, clients, actors, group):
        _, families = actors
        assignment = CarpoolAssignment.objects.create(
            carpool_group=group, date=MON, driver_family=families["a"]
        )
        resp = clients["b"].patch(
            f"/api/v1/assignments/{assignment.id}/",
            {"driver_family": str(families["c"].id), "notes": "C covers"},
        )
        assert resp.status_code == 200
        assignment.refresh_from_db()
        assert assignment.driver_family == families["c"]
        assert assignment.notes == "C covers"

    def test_driver_family_must_be_group_member(self, clients, actors, group):
        _, families = actors
        assignment = CarpoolAssignment.objects.create(
            carpool_group=group, date=MON, driver_family=families["a"]
        )
        resp = clients["a"].patch(
            f"/api/v1/assignments/{assignment.id}/",
            {"driver_family": str(families["d"].id)},
        )
        assert resp.status_code == 400

    def test_outsider_cannot_patch(self, clients, actors, group):
        _, families = actors
        assignment = CarpoolAssignment.objects.create(
            carpool_group=group, date=MON, driver_family=families["a"]
        )
        resp = clients["d"].patch(
            f"/api/v1/assignments/{assignment.id}/", {"notes": "hi"}
        )
        assert resp.status_code == 404
