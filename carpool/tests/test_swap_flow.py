"""Swap request flow end-to-end via the API, plus the expiry task."""

import datetime

import pytest
from django.utils import timezone

from carpool.models import CarpoolAssignment, CarpoolSwapRequest
from carpool.tasks import expire_stale_swap_requests

pytestmark = pytest.mark.django_db

MON = datetime.date(2026, 7, 6)


@pytest.fixture
def assignment(group, actors):
    _, families = actors
    return CarpoolAssignment.objects.create(
        carpool_group=group,
        date=MON,
        driver_family=families["a"],
        status="suggested",
        is_auto_suggested=True,
    )


class TestConfirm:
    def test_driver_family_confirms(self, clients, actors, assignment):
        users, _ = actors
        resp = clients["a"].post(f"/api/v1/assignments/{assignment.id}/confirm/")
        assert resp.status_code == 200
        assignment.refresh_from_db()
        assert assignment.status == "confirmed"
        assert assignment.driver_user == users["a"]

    def test_other_family_cannot_confirm(self, clients, assignment):
        resp = clients["b"].post(f"/api/v1/assignments/{assignment.id}/confirm/")
        assert resp.status_code == 403


class TestSwapFlow:
    def _request_swap(self, clients, assignment, families, target="b"):
        return clients["a"].post(
            f"/api/v1/assignments/{assignment.id}/swap-requests/",
            {"target_family": str(families[target].id), "reason": "Dentist"},
        )

    def test_accept_end_to_end(self, clients, actors, assignment):
        users, families = actors
        # 1. driver family requests a swap
        resp = self._request_swap(clients, assignment, families)
        assert resp.status_code == 201
        swap_id = resp.json()["id"]
        assignment.refresh_from_db()
        assert assignment.status == "swap_pending"

        # 2. target family accepts
        resp = clients["b"].post(
            f"/api/v1/swap-requests/{swap_id}/respond/", {"action": "accept"}
        )
        assert resp.status_code == 200
        assignment.refresh_from_db()
        assert assignment.driver_family == families["b"]
        assert assignment.driver_user == users["b"]
        assert assignment.status == "confirmed"
        swap = CarpoolSwapRequest.objects.get(pk=swap_id)
        assert swap.status == "accepted"
        assert swap.resolved_at is not None

    def test_reject_restores_assignment(self, clients, actors, assignment):
        _, families = actors
        swap_id = self._request_swap(clients, assignment, families).json()["id"]
        resp = clients["b"].post(
            f"/api/v1/swap-requests/{swap_id}/respond/", {"action": "reject"}
        )
        assert resp.status_code == 200
        assignment.refresh_from_db()
        assert assignment.driver_family == families["a"]
        assert assignment.status == "suggested"  # no driver_user was set
        assert (
            CarpoolSwapRequest.objects.get(pk=swap_id).status == "rejected"
        )

    def test_only_target_family_can_respond(self, clients, actors, assignment):
        _, families = actors
        swap_id = self._request_swap(clients, assignment, families).json()["id"]
        for tag in ["a", "c"]:
            resp = clients[tag].post(
                f"/api/v1/swap-requests/{swap_id}/respond/", {"action": "accept"}
            )
            assert resp.status_code == 403, tag

    def test_cannot_respond_twice(self, clients, actors, assignment):
        _, families = actors
        swap_id = self._request_swap(clients, assignment, families).json()["id"]
        clients["b"].post(
            f"/api/v1/swap-requests/{swap_id}/respond/", {"action": "accept"}
        )
        resp = clients["b"].post(
            f"/api/v1/swap-requests/{swap_id}/respond/", {"action": "accept"}
        )
        assert resp.status_code == 400

    def test_only_driver_family_can_request(self, clients, actors, assignment):
        _, families = actors
        resp = clients["b"].post(
            f"/api/v1/assignments/{assignment.id}/swap-requests/",
            {"target_family": str(families["c"].id)},
        )
        assert resp.status_code == 403

    def test_cannot_target_self_or_outsider(self, clients, actors, assignment):
        _, families = actors
        for target in ["a", "d"]:
            resp = self._request_swap(clients, assignment, families, target)
            assert resp.status_code == 400, target

    def test_single_pending_swap_per_assignment(
        self, clients, actors, assignment
    ):
        _, families = actors
        assert self._request_swap(clients, assignment, families).status_code == 201
        resp = self._request_swap(clients, assignment, families, "c")
        assert resp.status_code == 400


class TestExpiry:
    def test_expires_only_stale_pending(self, actors, group, assignment):
        users, families = actors
        stale = CarpoolSwapRequest.objects.create(
            assignment=assignment,
            requested_by=users["a"],
            target_family=families["b"],
        )
        CarpoolSwapRequest.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=72)
        )
        assignment.status = "swap_pending"
        assignment.save(update_fields=["status"])

        fresh_assignment = CarpoolAssignment.objects.create(
            carpool_group=group,
            date=MON + datetime.timedelta(days=1),
            driver_family=families["a"],
            status="swap_pending",
        )
        fresh = CarpoolSwapRequest.objects.create(
            assignment=fresh_assignment,
            requested_by=users["a"],
            target_family=families["c"],
        )

        assert expire_stale_swap_requests() == 1

        stale.refresh_from_db()
        fresh.refresh_from_db()
        assignment.refresh_from_db()
        fresh_assignment.refresh_from_db()
        assert stale.status == "expired"
        assert stale.resolved_at is not None
        assert fresh.status == "pending"
        assert assignment.status == "suggested"  # released from limbo
        assert fresh_assignment.status == "swap_pending"

    def test_expired_assignment_with_driver_returns_to_confirmed(
        self, actors, group
    ):
        users, families = actors
        assignment = CarpoolAssignment.objects.create(
            carpool_group=group,
            date=MON,
            driver_family=families["a"],
            driver_user=users["a"],
            status="swap_pending",
        )
        swap = CarpoolSwapRequest.objects.create(
            assignment=assignment,
            requested_by=users["a"],
            target_family=families["b"],
        )
        CarpoolSwapRequest.objects.filter(pk=swap.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=72)
        )
        expire_stale_swap_requests()
        assignment.refresh_from_db()
        assert assignment.status == "confirmed"
