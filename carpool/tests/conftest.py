import datetime

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from carpool.models import (
    CarpoolGroup,
    CarpoolGroupMember,
    CarpoolRotationOrder,
    CarpoolRotationRule,
)
from families.models import Family, FamilyMember
from schools.models import School


def make_user_with_family(tag):
    user = User.objects.create_user(
        email=f"{tag}@example.com", clerk_user_id=f"user_{tag}"
    )
    family = Family.objects.create(name=f"Family {tag.upper()}", created_by=user)
    FamilyMember.objects.create(
        family=family, user=user, role=FamilyMember.Role.OWNER
    )
    return user, family


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
    """Three families in a group (A admin), one outsider (D)."""
    users, families = {}, {}
    for tag in ["a", "b", "c", "d"]:
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
    for tag in ["b", "c"]:
        CarpoolGroupMember.objects.create(
            carpool_group=group, family=families[tag], role="member"
        )
    return group


def make_rule(
    group,
    families_in_order,
    rotation_type="round_robin",
    cycle_days=(0, 1, 2, 3, 4),
    start_date=datetime.date(2026, 7, 6),  # a Monday
    weights=None,
):
    rule = CarpoolRotationRule.objects.create(
        carpool_group=group,
        rotation_type=rotation_type,
        cycle_days=list(cycle_days),
        start_date=start_date,
    )
    weights = weights or [1] * len(families_in_order)
    for position, (family, weight) in enumerate(
        zip(families_in_order, weights)
    ):
        CarpoolRotationOrder.objects.create(
            rotation_rule=rule, family=family, position=position, weight=weight
        )
    return rule


@pytest.fixture
def clients(actors):
    users, _ = actors
    result = {}
    for tag, user in users.items():
        client = APIClient()
        client.force_authenticate(user=user)
        result[tag] = client
    return result
