"""Carpool group invites (email + accept) and leaving a group."""

import uuid

import pytest
from django.core import mail
from rest_framework.test import APIClient

from carpool.models import CarpoolGroupInvite, CarpoolGroupMember
from carpool.tests.conftest import make_user_with_family

pytestmark = pytest.mark.django_db


class TestInvite:
    def test_admin_invites_sends_email_with_code(self, group, clients):
        mail.outbox.clear()
        resp = clients["a"].post(
            f"/api/v1/carpool-groups/{group.id}/invite/",
            {"email": "New.Parent@Example.com"},
            format="json",
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["email"] == "new.parent@example.com"  # lowercased
        assert body["invite_code"] == group.invite_code

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert "new.parent@example.com" in message.to
        assert group.invite_code in message.body
        invite = CarpoolGroupInvite.objects.get(id=body["id"])
        assert str(invite.token) in message.body  # deep link token

    def test_non_admin_member_forbidden(self, group, clients):
        resp = clients["b"].post(
            f"/api/v1/carpool-groups/{group.id}/invite/",
            {"email": "x@example.com"},
            format="json",
        )
        assert resp.status_code == 403

    def test_outsider_cannot_see_group(self, group, clients):
        resp = clients["d"].post(
            f"/api/v1/carpool-groups/{group.id}/invite/",
            {"email": "x@example.com"},
            format="json",
        )
        assert resp.status_code == 404

    def test_invalid_email_400(self, group, clients):
        resp = clients["a"].post(
            f"/api/v1/carpool-groups/{group.id}/invite/",
            {"email": "not-an-email"},
            format="json",
        )
        assert resp.status_code == 400
        assert "email" in resp.json()["error"]["details"]

    def test_reinvite_pending_does_not_duplicate(self, group, clients):
        for _ in range(2):
            resp = clients["a"].post(
                f"/api/v1/carpool-groups/{group.id}/invite/",
                {"email": "dup@example.com"},
                format="json",
            )
            assert resp.status_code == 201
        assert (
            CarpoolGroupInvite.objects.filter(
                group=group, email="dup@example.com", status="pending"
            ).count()
            == 1
        )


class TestAccept:
    def _invite(self, group, clients, email):
        clients["a"].post(
            f"/api/v1/carpool-groups/{group.id}/invite/",
            {"email": email},
            format="json",
        )
        return CarpoolGroupInvite.objects.get(group=group, email=email)

    def test_accept_adds_family_as_member(self, group, clients):
        user_e, family_e = make_user_with_family("e")
        client_e = APIClient()
        client_e.force_authenticate(user=user_e)
        invite = self._invite(group, clients, "e@example.com")

        resp = client_e.post(
            "/api/v1/carpool-group-invites/accept/",
            {"token": str(invite.token), "family": str(family_e.id)},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["member"]["role"] == "member"
        assert CarpoolGroupMember.objects.filter(
            carpool_group=group, family=family_e
        ).exists()
        invite.refresh_from_db()
        assert invite.status == "accepted"
        assert invite.accepted_at is not None

        # Re-accepting is a no-op (idempotent).
        resp2 = client_e.post(
            "/api/v1/carpool-group-invites/accept/",
            {"token": str(invite.token), "family": str(family_e.id)},
            format="json",
        )
        # token is no longer pending → treated as not found
        assert resp2.status_code == 404
        assert (
            CarpoolGroupMember.objects.filter(
                carpool_group=group, family=family_e
            ).count()
            == 1
        )

    def test_accept_invalid_token_404(self, group, clients):
        user_e, family_e = make_user_with_family("e")
        client_e = APIClient()
        client_e.force_authenticate(user=user_e)
        resp = client_e.post(
            "/api/v1/carpool-group-invites/accept/",
            {"token": str(uuid.uuid4()), "family": str(family_e.id)},
            format="json",
        )
        assert resp.status_code == 404

    def test_accept_family_not_yours_400(self, group, clients, actors):
        _, families = actors
        user_e, _ = make_user_with_family("e")
        client_e = APIClient()
        client_e.force_authenticate(user=user_e)
        invite = self._invite(group, clients, "e@example.com")
        resp = client_e.post(
            "/api/v1/carpool-group-invites/accept/",
            {"token": str(invite.token), "family": str(families["a"].id)},
            format="json",
        )
        assert resp.status_code == 400


class TestLeave:
    def test_member_leaves_removes_only_their_family(self, group, clients, actors):
        _, families = actors
        resp = clients["b"].post(f"/api/v1/carpool-groups/{group.id}/leave/")
        assert resp.status_code == 204
        assert not CarpoolGroupMember.objects.filter(
            carpool_group=group, family=families["b"]
        ).exists()
        # a (admin) and c remain
        assert group.members.count() == 2

    def test_only_admin_leaving_promotes_oldest_remaining(
        self, group, clients, actors
    ):
        _, families = actors
        # a is the only admin; b joined before c (conftest order) → b inherits.
        resp = clients["a"].post(f"/api/v1/carpool-groups/{group.id}/leave/")
        assert resp.status_code == 204
        assert not group.members.filter(family=families["a"]).exists()
        heir = group.members.order_by("joined_at").first()
        assert heir.family_id == families["b"].id
        assert heir.role == "admin"

    def test_non_member_cannot_leave(self, group, clients):
        resp = clients["d"].post(f"/api/v1/carpool-groups/{group.id}/leave/")
        assert resp.status_code in (403, 404)


class TestGroupSerializerFields:
    def test_list_includes_member_count_and_school_name(self, group, clients):
        resp = clients["a"].get("/api/v1/carpool-groups/")
        assert resp.status_code == 200
        row = resp.json()["results"][0]
        assert row["member_count"] == 3
        assert row["school_name"] == group.school.name
