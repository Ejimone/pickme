import pytest

from trips.models import Trip, TripStop

pytestmark = pytest.mark.django_db


class TestTripCreation:
    def test_create_trip_with_stops(self, clients, group, children, school):
        response = clients["a"].post(
            "/api/v1/trips/",
            {
                "carpool_group": str(group.id),
                "date": "2026-07-07",
                "tracking_mode": "live_gps",
                "stops": [
                    {
                        "school": str(school.id),
                        "sequence_order": 1,
                        "children": [str(children["a"].id), str(children["b"].id)],
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        trip = Trip.objects.get(id=response.data["id"])
        assert trip.driver.clerk_user_id == "user_a"
        assert trip.status == Trip.Status.NOT_STARTED
        stop = trip.stops.get()
        assert stop.children.count() == 2

    def test_stop_requires_school_or_activity(self, clients, children):
        response = clients["a"].post(
            "/api/v1/trips/",
            {
                "date": "2026-07-07",
                "stops": [
                    {"sequence_order": 1, "children": [str(children["a"].id)]}
                ],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_cannot_include_unrelated_child(self, clients, children, school):
        # Child D's family shares no family or carpool group with driver A
        response = clients["a"].post(
            "/api/v1/trips/",
            {
                "date": "2026-07-07",
                "stops": [
                    {
                        "school": str(school.id),
                        "sequence_order": 1,
                        "children": [str(children["d"].id)],
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == 400


class TestTripScoping:
    def test_unauthenticated_rejected(self, trip):
        from rest_framework.test import APIClient

        response = APIClient().get("/api/v1/trips/")
        assert response.status_code == 401

    def test_outsider_sees_no_trips(self, clients, trip):
        response = clients["d"].get("/api/v1/trips/")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_outsider_cannot_retrieve_trip(self, clients, trip):
        response = clients["d"].get(f"/api/v1/trips/{trip.id}/")
        assert response.status_code == 404

    def test_group_member_sees_trip(self, clients, trip):
        response = clients["b"].get(f"/api/v1/trips/{trip.id}/")
        assert response.status_code == 200
        assert len(response.data["stops"]) == 1

    def test_date_filter(self, clients, trip):
        assert (
            clients["a"].get("/api/v1/trips/?date=2026-07-06").data["results"]
        )
        assert (
            clients["a"].get("/api/v1/trips/?date=2026-01-01").data["results"] == []
        )


class TestTripLifecycle:
    def test_start_and_end(self, clients, trip):
        response = clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        assert response.status_code == 200
        trip.refresh_from_db()
        assert trip.status == Trip.Status.IN_PROGRESS
        assert trip.started_at is not None
        assert trip.stops.get().status == TripStop.Status.EN_ROUTE

        response = clients["a"].post(f"/api/v1/trips/{trip.id}/end/")
        assert response.status_code == 200
        trip.refresh_from_db()
        assert trip.status == Trip.Status.COMPLETED
        assert trip.ended_at is not None

    def test_cannot_start_twice(self, clients, trip):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        response = clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        assert response.status_code == 400

    def test_cannot_end_unstarted(self, clients, trip):
        response = clients["a"].post(f"/api/v1/trips/{trip.id}/end/")
        assert response.status_code == 400

    def test_non_driver_cannot_start(self, clients, trip):
        response = clients["b"].post(f"/api/v1/trips/{trip.id}/start/")
        assert response.status_code == 403


class TestStopUpdates:
    def _start(self, clients, trip):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        return trip.stops.get()

    def test_arrived_then_picked_up(self, clients, trip):
        stop = self._start(clients, trip)
        url = f"/api/v1/trips/{trip.id}/stops/{stop.id}/"

        response = clients["a"].patch(url, {"status": "arrived"}, format="json")
        assert response.status_code == 200
        stop.refresh_from_db()
        assert stop.status == TripStop.Status.ARRIVED
        assert stop.actual_arrival_time is not None

        response = clients["a"].patch(url, {"status": "picked_up"}, format="json")
        assert response.status_code == 200
        stop.refresh_from_db()
        assert stop.status == TripStop.Status.PICKED_UP
        assert all(
            entry.picked_up_at is not None for entry in stop.children.all()
        )

    def test_picked_up_subset_of_children(self, clients, trip, children):
        stop = self._start(clients, trip)
        url = f"/api/v1/trips/{trip.id}/stops/{stop.id}/"
        clients["a"].patch(url, {"status": "arrived"}, format="json")
        response = clients["a"].patch(
            url,
            {"status": "picked_up", "children": [str(children["a"].id)]},
            format="json",
        )
        assert response.status_code == 200
        entries = {e.child_id: e.picked_up_at for e in stop.children.all()}
        assert entries[children["a"].id] is not None
        assert entries[children["b"].id] is None

    def test_invalid_transition_rejected(self, clients, trip):
        stop = self._start(clients, trip)
        # en_route → picked_up skips "arrived"
        response = clients["a"].patch(
            f"/api/v1/trips/{trip.id}/stops/{stop.id}/",
            {"status": "picked_up"},
            format="json",
        )
        assert response.status_code == 400

    def test_non_driver_cannot_update_stop(self, clients, trip):
        stop = self._start(clients, trip)
        response = clients["b"].patch(
            f"/api/v1/trips/{trip.id}/stops/{stop.id}/",
            {"status": "arrived"},
            format="json",
        )
        assert response.status_code == 403


class TestLocationEndpoints:
    def test_rest_ping_and_latest(self, clients, trip):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        response = clients["a"].post(
            f"/api/v1/trips/{trip.id}/location/",
            {"lat": "41.878100", "lng": "-87.629800", "speed": 8.2},
            format="json",
        )
        assert response.status_code == 201
        assert trip.pings.count() == 1

        response = clients["b"].get(f"/api/v1/trips/{trip.id}/location/latest/")
        assert response.status_code == 200
        assert response.data["lat"] == "41.878100"

    def test_ping_requires_in_progress_trip(self, clients, trip):
        response = clients["a"].post(
            f"/api/v1/trips/{trip.id}/location/",
            {"lat": "41.878100", "lng": "-87.629800"},
            format="json",
        )
        assert response.status_code == 400

    def test_non_driver_cannot_ping(self, clients, trip):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        response = clients["b"].post(
            f"/api/v1/trips/{trip.id}/location/",
            {"lat": "41.878100", "lng": "-87.629800"},
            format="json",
        )
        assert response.status_code == 403

    def test_latest_404_when_no_pings(self, clients, trip):
        response = clients["a"].get(f"/api/v1/trips/{trip.id}/location/latest/")
        assert response.status_code == 404
        assert response.data["error"]["code"] == "not_found"
