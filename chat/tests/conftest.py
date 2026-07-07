import datetime

import pytest
from rest_framework.test import APIClient

from carpool.models import CarpoolGroup, CarpoolGroupMember
from carpool.tests.conftest import make_user_with_family
from chat.models import ChatThread
from schools.models import School


# The in-memory channel layer is set globally by the root conftest's
# _in_memory_channels autouse fixture.


@pytest.fixture
def school(db):
    return School.objects.create(
        name="Lincoln Elementary",
        address="1 Main St",
        timezone="America/Chicago",
        default_dismissal_time=datetime.time(15, 0),
    )


@pytest.fixture
def actors(db):
    """Group members a (admin) and b, plus outsider d."""
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
def thread(group):
    """The carpool-group thread the signal auto-creates on group save."""
    return ChatThread.objects.get(carpool_group=group)


@pytest.fixture
def clients(actors):
    users, _ = actors
    result = {}
    for tag, user in users.items():
        client = APIClient()
        client.force_authenticate(user=user)
        result[tag] = client
    return result
