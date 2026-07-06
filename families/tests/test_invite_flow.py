import pytest

from families.models import FamilyInvite, FamilyMember

pytestmark = pytest.mark.django_db


def invite(client, family, email="b@example.com"):
    return client.post(
        f"/api/v1/families/{family.id}/members/invite/", {"email": email}
    )


class TestInviteFlow:
    def test_invite_then_accept(self, client_a, client_b, family_a, user_b):
        resp = invite(client_a, family_a)
        assert resp.status_code == 201
        token = FamilyInvite.objects.get(pk=resp.json()["id"]).token

        resp = client_b.post("/api/v1/family-invites/accept/", {"token": token})
        assert resp.status_code == 201
        assert resp.json()["member"]["role"] == "member"
        assert FamilyMember.objects.filter(
            family=family_a, user=user_b
        ).exists()

        # family B's user can now see family A
        assert (
            client_b.get(f"/api/v1/families/{family_a.id}/").status_code == 200
        )

        invite_row = FamilyInvite.objects.get(token=token)
        assert invite_row.status == FamilyInvite.Status.ACCEPTED
        assert invite_row.responded_at is not None

    def test_accept_is_idempotent_for_existing_member(
        self, client_a, client_b, family_a, user_b
    ):
        token1 = FamilyInvite.objects.get(
            pk=invite(client_a, family_a).json()["id"]
        ).token
        client_b.post("/api/v1/family-invites/accept/", {"token": token1})
        token2 = FamilyInvite.objects.get(
            pk=invite(client_a, family_a, email="b+again@example.com").json()["id"]
        ).token

        resp = client_b.post("/api/v1/family-invites/accept/", {"token": token2})
        assert resp.status_code == 200  # already a member, not re-created
        assert (
            FamilyMember.objects.filter(family=family_a, user=user_b).count() == 1
        )

    def test_used_token_rejected(self, client_a, client_b, family_a):
        token = FamilyInvite.objects.get(
            pk=invite(client_a, family_a).json()["id"]
        ).token
        client_b.post("/api/v1/family-invites/accept/", {"token": token})
        resp = client_b.post("/api/v1/family-invites/accept/", {"token": token})
        assert resp.status_code == 404

    def test_bogus_token_rejected(self, client_b):
        resp = client_b.post(
            "/api/v1/family-invites/accept/",
            {"token": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == 404

    def test_nonmember_cannot_invite(self, client_b, family_a):
        resp = invite(client_b, family_a, email="x@example.com")
        assert resp.status_code == 404

    def test_duplicate_pending_invite_rejected(self, client_a, family_a):
        assert invite(client_a, family_a).status_code == 201
        resp = invite(client_a, family_a)
        assert resp.status_code == 400

    def test_existing_member_email_rejected(self, client_a, family_a, user_a):
        resp = invite(client_a, family_a, email=user_a.email)
        assert resp.status_code == 400


class TestMemberRemoval:
    def test_owner_removes_member(self, client_a, client_b, family_a, user_b):
        member = FamilyMember.objects.create(family=family_a, user=user_b)
        resp = client_a.delete(
            f"/api/v1/families/{family_a.id}/members/{member.id}/"
        )
        assert resp.status_code == 204
        assert not FamilyMember.objects.filter(pk=member.pk).exists()

    def test_member_cannot_remove_others(
        self, client_a, client_b, family_a, user_a, user_b
    ):
        FamilyMember.objects.create(family=family_a, user=user_b)
        owner_row = FamilyMember.objects.get(family=family_a, user=user_a)
        resp = client_b.delete(
            f"/api/v1/families/{family_a.id}/members/{owner_row.id}/"
        )
        assert resp.status_code == 403

    def test_owner_cannot_be_removed(self, client_a, family_a, user_a):
        owner_row = FamilyMember.objects.get(family=family_a, user=user_a)
        resp = client_a.delete(
            f"/api/v1/families/{family_a.id}/members/{owner_row.id}/"
        )
        assert resp.status_code == 400

    def test_only_owner_can_rename(self, client_b, family_a, user_b):
        FamilyMember.objects.create(family=family_a, user=user_b)
        resp = client_b.patch(
            f"/api/v1/families/{family_a.id}/", {"name": "Renamed"}
        )
        assert resp.status_code == 403
