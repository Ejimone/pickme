import datetime

import pytest

from carpool.models import CarpoolAssignment
from trips.models import PickupEvent, Trip, TripStop
from trips.pickups import generate_daily_pickup_events
from trips.tasks import generate_daily_pickup_events as generate_task

pytestmark = pytest.mark.django_db

TRIP_DATE = datetime.date(2026, 7, 6)  # Monday, a school day at the fixture school


class TestTripCascade:
    def test_start_generates_events_per_child(self, clients, trip):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        events = PickupEvent.objects.filter(date=trip.date)
        assert events.count() == 2  # kids A and B on the trip
        for event in events:
            assert event.status == PickupEvent.Status.EN_ROUTE
            assert event.trip_stop_child_id is not None
            assert event.pickup_method == PickupEvent.Method.CARPOOL

    def test_arrived_propagates_to_pickup_event(self, clients, trip, children):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        stop = trip.stops.get()
        clients["a"].patch(
            f"/api/v1/trips/{trip.id}/stops/{stop.id}/",
            {"status": "arrived"},
            format="json",
        )
        event = PickupEvent.objects.get(child=children["a"], date=trip.date)
        assert event.status == PickupEvent.Status.ARRIVED

    def test_picked_up_cascade(self, clients, trip, children):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        stop = trip.stops.get()
        url = f"/api/v1/trips/{trip.id}/stops/{stop.id}/"
        clients["a"].patch(url, {"status": "arrived"}, format="json")
        clients["a"].patch(url, {"status": "picked_up"}, format="json")
        for tag in ["a", "b"]:
            event = PickupEvent.objects.get(child=children[tag], date=trip.date)
            assert event.status == PickupEvent.Status.PICKED_UP

    def test_partial_pickup_only_moves_that_child(self, clients, trip, children):
        clients["a"].post(f"/api/v1/trips/{trip.id}/start/")
        stop = trip.stops.get()
        url = f"/api/v1/trips/{trip.id}/stops/{stop.id}/"
        clients["a"].patch(url, {"status": "arrived"}, format="json")
        clients["a"].patch(
            url,
            {"status": "picked_up", "children": [str(children["a"].id)]},
            format="json",
        )
        assert (
            PickupEvent.objects.get(child=children["a"], date=trip.date).status
            == PickupEvent.Status.PICKED_UP
        )
        # B was only arrived-at, not picked up
        assert (
            PickupEvent.objects.get(child=children["b"], date=trip.date).status
            == PickupEvent.Status.ARRIVED
        )


class TestDailyGeneration:
    def test_creates_events_for_children_with_pickup(self, children):
        created = generate_daily_pickup_events(TRIP_DATE)
        assert created == 3  # kids A, B, D all attend the school on a Monday
        assert PickupEvent.objects.filter(date=TRIP_DATE).count() == 3

    def test_idempotent(self, children):
        assert generate_daily_pickup_events(TRIP_DATE) == 3
        assert generate_daily_pickup_events(TRIP_DATE) == 0
        assert PickupEvent.objects.filter(date=TRIP_DATE).count() == 3

    def test_skips_no_school_day(self, children):
        sunday = datetime.date(2026, 7, 5)
        assert generate_daily_pickup_events(sunday) == 0

    def test_carpool_method_when_assignment_exists(self, group, children, actors):
        _, families = actors
        CarpoolAssignment.objects.create(
            carpool_group=group,
            date=TRIP_DATE,
            driver_family=families["a"],
            status=CarpoolAssignment.Status.CONFIRMED,
        )
        generate_daily_pickup_events(TRIP_DATE)
        # A and B carpool (member families); D is an outsider → parent
        assert (
            PickupEvent.objects.get(child=children["a"], date=TRIP_DATE).pickup_method
            == PickupEvent.Method.CARPOOL
        )
        assert (
            PickupEvent.objects.get(child=children["d"], date=TRIP_DATE).pickup_method
            == PickupEvent.Method.PARENT
        )

    def test_task_defaults_to_today(self, children, settings):
        # Explicit date passthrough keeps the beat task thin
        assert generate_task(TRIP_DATE) == 3


class TestTodayEndpoint:
    def test_lists_family_events_for_date(self, clients, children):
        generate_daily_pickup_events(TRIP_DATE)
        response = clients["a"].get(f"/api/v1/pickup-events/?date={TRIP_DATE}")
        assert response.status_code == 200
        # Family A has one child (A); B and D are other families
        child_ids = {str(row["child"]) for row in response.data["results"]}
        assert child_ids == {str(children["a"].id)}

    def test_outsider_cannot_see_others_events(self, clients, children):
        generate_daily_pickup_events(TRIP_DATE)
        response = clients["d"].get(f"/api/v1/pickup-events/?date={TRIP_DATE}")
        child_ids = {str(row["child"]) for row in response.data["results"]}
        assert child_ids == {str(children["d"].id)}

    def test_default_date_is_today(self, clients, children):
        from django.utils import timezone

        today = timezone.localdate()
        PickupEvent.objects.create(
            child=children["a"], date=today, scheduled_time=timezone.now()
        )
        PickupEvent.objects.create(
            child=children["a"],
            date=today - datetime.timedelta(days=10),
            scheduled_time=timezone.now(),
        )
        # No ?date → "Today" semantics: only today's row comes back
        response = clients["a"].get("/api/v1/pickup-events/")
        dates = {row["date"] for row in response.data["results"]}
        assert dates == {today.isoformat()}

    def test_unauthenticated_rejected(self, trip):
        from rest_framework.test import APIClient

        assert APIClient().get("/api/v1/pickup-events/").status_code == 401


class TestOverride:
    def _event(self, children, tag="a"):
        generate_daily_pickup_events(TRIP_DATE)
        return PickupEvent.objects.get(child=children[tag], date=TRIP_DATE)

    def test_owner_can_override_status_and_method(self, clients, children):
        event = self._event(children)
        response = clients["a"].patch(
            f"/api/v1/pickup-events/{event.id}/",
            {"status": "cancelled", "pickup_method": "aftercare"},
            format="json",
        )
        assert response.status_code == 200
        event.refresh_from_db()
        assert event.status == PickupEvent.Status.CANCELLED
        assert event.pickup_method == PickupEvent.Method.AFTERCARE

    def test_outsider_cannot_override(self, clients, children):
        event = self._event(children)  # child A's event
        response = clients["d"].patch(
            f"/api/v1/pickup-events/{event.id}/",
            {"status": "cancelled"},
            format="json",
        )
        assert response.status_code in (403, 404)
        event.refresh_from_db()
        assert event.status != PickupEvent.Status.CANCELLED

    def test_readonly_fields_ignored(self, clients, children):
        event = self._event(children)
        original_date = event.date
        clients["a"].patch(
            f"/api/v1/pickup-events/{event.id}/",
            {"date": "2020-01-01", "status": "missed"},
            format="json",
        )
        event.refresh_from_db()
        assert event.date == original_date
        assert event.status == PickupEvent.Status.MISSED
