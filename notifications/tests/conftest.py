import datetime

import pytest
from rest_framework.test import APIClient

from carpool.models import CarpoolGroup, CarpoolGroupMember
from carpool.tests.conftest import make_user_with_family
from families.models import Child
from schools.models import School


# The in-memory channel layer is set globally by the root conftest's
# _in_memory_channels autouse fixture.


@pytest.fixture(autouse=True)
def no_push_dispatch(monkeypatch):
    """Keep the post_save signal's push dispatch off the real broker. Task
    tests exercise `send_push_notification` directly instead."""
    from notifications.tasks import send_push_notification

    monkeypatch.setattr(send_push_notification, "delay", lambda *a, **k: None)


@pytest.fixture
def school(db):
    return School.objects.create(
        name="Lincoln Elementary",
        address="1 Main St",
        timezone="UTC",
        default_dismissal_time=datetime.time(15, 0),
    )


@pytest.fixture
def actors(db):
    """Group families a (admin) and b, plus outsider d."""
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
def clients(actors):
    users, _ = actors
    result = {}
    for tag, user in users.items():
        client = APIClient()
        client.force_authenticate(user=user)
        result[tag] = client
    return result
