import datetime

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from families.models import Child, Family, FamilyMember
from schools.models import School


@pytest.fixture
def user_a(db):
    return User.objects.create_user(email="a@example.com", clerk_user_id="user_a")


@pytest.fixture
def user_b(db):
    return User.objects.create_user(email="b@example.com", clerk_user_id="user_b")


def make_family(owner, name):
    family = Family.objects.create(name=name, created_by=owner)
    FamilyMember.objects.create(
        family=family, user=owner, role=FamilyMember.Role.OWNER
    )
    return family


@pytest.fixture
def family_a(user_a):
    return make_family(user_a, "Family A")


@pytest.fixture
def family_b(user_b):
    return make_family(user_b, "Family B")


@pytest.fixture
def school(db):
    return School.objects.create(
        name="Lincoln Elementary",
        address="1 Main St",
        timezone="America/Chicago",
        default_dismissal_time=datetime.time(15, 0),
    )


@pytest.fixture
def child_a(family_a, school):
    return Child.objects.create(
        family=family_a, school=school, full_name="Ada A"
    )


@pytest.fixture
def child_b(family_b, school):
    return Child.objects.create(
        family=family_b, school=school, full_name="Ben B"
    )


@pytest.fixture
def client_a(user_a):
    client = APIClient()
    client.force_authenticate(user=user_a)
    return client


@pytest.fixture
def client_b(user_b):
    client = APIClient()
    client.force_authenticate(user=user_b)
    return client
