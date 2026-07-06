import pytest
from django.utils import timezone

from trips import services
from trips.models import LocationPing, Trip
from trips.services import FakeMapsService, acquire_eta_lock, record_ping
from trips.tasks import recalculate_trip_eta

pytestmark = pytest.mark.django_db


def make_ping(trip):
    return LocationPing.objects.create(
        trip=trip, lat="41.878100", lng="-87.629800", recorded_at=timezone.now()
    )


class TestRecalculateTripEta:
    def test_updates_next_stop_eta(self, trip):
        trip.status = Trip.Status.IN_PROGRESS
        trip.save()
        trip.stops.update(status="en_route")
        make_ping(trip)

        before = timezone.now()
        result = recalculate_trip_eta(str(trip.id))

        stop = trip.stops.get()
        stop.refresh_from_db()
        assert result is not None
        assert stop.eta is not None
        expected_seconds = FakeMapsService().eta_seconds(
            (41.8781, -87.6298), (trip.stops.get().school.lat, stop.school.lng)
        )
        assert (
            abs((stop.eta - before).total_seconds() - expected_seconds) < 5
        )

    def test_noop_when_trip_not_in_progress(self, trip):
        make_ping(trip)
        assert recalculate_trip_eta(str(trip.id)) is None
        assert trip.stops.get().eta is None

    def test_noop_without_pings(self, trip):
        trip.status = Trip.Status.IN_PROGRESS
        trip.save()
        assert recalculate_trip_eta(str(trip.id)) is None

    def test_noop_when_all_stops_terminal(self, trip):
        trip.status = Trip.Status.IN_PROGRESS
        trip.save()
        trip.stops.update(status="picked_up")
        make_ping(trip)
        assert recalculate_trip_eta(str(trip.id)) is None


class TestEtaThrottle:
    def test_dispatch_only_when_lock_free(self, trip, monkeypatch):
        trip.status = Trip.Status.IN_PROGRESS
        trip.save()
        calls = []
        monkeypatch.setattr(
            "trips.tasks.recalculate_trip_eta.delay",
            lambda trip_id: calls.append(trip_id),
        )

        lock_results = iter([True, False])  # first acquire wins, second is held
        monkeypatch.setattr(
            services, "acquire_eta_lock", lambda trip_id: next(lock_results)
        )

        data = {"lat": "41.878100", "lng": "-87.629800"}
        record_ping(trip, data)
        record_ping(trip, data)

        assert calls == [str(trip.id)]
        assert trip.pings.count() == 2  # pings always persist; only ETA throttles

    def test_lock_sets_nx_with_ttl(self, settings, monkeypatch):
        captured = {}

        class FakeRedis:
            def set(self, key, value, nx=None, ex=None):
                captured.update(key=key, nx=nx, ex=ex)
                return True

        monkeypatch.setattr(
            services.redis.Redis, "from_url", classmethod(lambda cls, url: FakeRedis())
        )
        assert acquire_eta_lock("abc") is True
        assert captured == {
            "key": "eta_lock:abc",
            "nx": True,
            "ex": settings.ETA_THROTTLE_SECONDS,
        }
