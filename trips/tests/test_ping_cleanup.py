import pytest
from django.utils import timezone

from trips import tasks
from trips.models import LocationPing
from trips.tasks import cleanup_old_location_pings

pytestmark = pytest.mark.django_db


def make_ping(trip, days_ago):
    return LocationPing.objects.create(
        trip=trip,
        lat="41.878100",
        lng="-87.629800",
        recorded_at=timezone.now() - timezone.timedelta(days=days_ago),
    )


def test_deletes_old_pings_in_batches(trip, monkeypatch):
    monkeypatch.setattr(tasks, "CLEANUP_BATCH_SIZE", 2)
    old = [make_ping(trip, days_ago=31 + i) for i in range(5)]
    recent = [make_ping(trip, days_ago=d) for d in (0, 15, 29)]

    deleted = cleanup_old_location_pings()

    assert deleted == len(old)
    remaining = set(LocationPing.objects.values_list("id", flat=True))
    assert remaining == {p.id for p in recent}


def test_respects_retention_setting(trip, settings):
    settings.LOCATION_PING_RETENTION_DAYS = 7
    make_ping(trip, days_ago=8)
    keep = make_ping(trip, days_ago=6)

    assert cleanup_old_location_pings() == 1
    assert list(LocationPing.objects.values_list("id", flat=True)) == [keep.id]


def test_idempotent_when_nothing_to_delete(trip):
    make_ping(trip, days_ago=1)
    assert cleanup_old_location_pings() == 0
    assert cleanup_old_location_pings() == 0
    assert LocationPing.objects.count() == 1
