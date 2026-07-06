import datetime

import pytest
from rest_framework.test import APIClient

from carpool.models import CarpoolGroup, CarpoolGroupMember
from carpool.tests.conftest import make_user_with_family
from families.models import Child
from schools.models import School
from trips.models import Trip, TripStop, TripStopChild


@pytest.fixture(autouse=True)
def in_memory_channel_layer(settings):
    """Trips code broadcasts on every mutation; keep it off Redis in tests."""
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }
    from channels.layers import channel_layers

    channel_layers.backends = {}
    yield
    channel_layers.backends = {}


@pytest.fixture(autouse=True)
def no_eta_dispatch(monkeypatch):
    """Keep record_ping off real Redis/Celery; ETA tests override this."""
    monkeypatch.setattr("trips.services.acquire_eta_lock", lambda trip_id: False)


@pytest.fixture
def school(db):
    return School.objects.create(
        name="Lincoln Elementary",
        address="1 Main St",
        timezone="America/Chicago",
        default_dismissal_time=datetime.time(15, 0),
        lat="41.900000",
        lng="-87.650000",
    )


@pytest.fixture
def actors(db):
    """Driver family (a), co-member family (b), outsider family (d)."""
    users, families = {}, {}
    for tag in ["a", "b", "d"]:
        users[tag], families[tag] = make_user_with_family(tag)
    return users, families


@pytest.fixture
def group(actors, school):
    users, families = actors
    group = CarpoolGroup.objects.create(
        school=school, name="Morning Crew", created_by=users["a"]
    )
    CarpoolGroupMember.objects.create(
        carpool_group=group, family=families["a"], role="admin"
    )
    CarpoolGroupMember.objects.create(
        carpool_group=group, family=families["b"], role="member"
    )
    return group


@pytest.fixture
def children(actors, school):
    _, families = actors
    return {
        tag: Child.objects.create(
            family=families[tag], school=school, full_name=f"Kid {tag.upper()}"
        )
        for tag in ["a", "b", "d"]
    }


@pytest.fixture
def trip(actors, group, children):
    users, _ = actors
    trip = Trip.objects.create(
        driver=users["a"], carpool_group=group, date=datetime.date(2026, 7, 6)
    )
    stop = TripStop.objects.create(trip=trip, school=group.school, sequence_order=1)
    for tag in ["a", "b"]:
        TripStopChild.objects.create(trip_stop=stop, child=children[tag])
    return trip


@pytest.fixture
def clients(actors):
    users, _ = actors
    result = {}
    for tag, user in users.items():
        client = APIClient()
        client.force_authenticate(user=user)
        result[tag] = client
    return result
