"""Stage 2: effective pickup time resolution (schools/services.py).

The fixture school is in America/Chicago (UTC-5 in July / CDT), so
3:00pm local = 20:00 UTC.
"""

import datetime

import pytest

from accounts.models import User
from families.models import Activity, Child, Family, FamilyMember
from schools.models import School, SchoolCalendarException
from schools.services import resolve_effective_pickup_time

pytestmark = pytest.mark.django_db

MONDAY = datetime.date(2026, 7, 6)
WEDNESDAY = datetime.date(2026, 7, 8)
SATURDAY = datetime.date(2026, 7, 11)


def utc(hour, minute=0, date=MONDAY):
    return datetime.datetime.combine(
        date, datetime.time(hour, minute), tzinfo=datetime.timezone.utc
    )


@pytest.fixture
def child(db):
    user = User.objects.create_user(email="p@x.com", clerk_user_id="user_p")
    family = Family.objects.create(name="F", created_by=user)
    FamilyMember.objects.create(family=family, user=user, role="owner")
    school = School.objects.create(
        name="Lincoln",
        address="1 Main St",
        timezone="America/Chicago",
        default_dismissal_time=datetime.time(15, 0),
        early_dismissal_days={"2": "13:30"},  # Wednesdays
    )
    return Child.objects.create(family=family, school=school, full_name="Ada")


def add_activity(child, day, end, start=datetime.time(15, 30)):
    return Activity.objects.create(
        child=child,
        name="Practice",
        day_of_week=day,
        start_time=start,
        end_time=end,
    )


def add_exception(child, date, dismissal_time, reason="Exception"):
    return SchoolCalendarException.objects.create(
        school=child.school, date=date, dismissal_time=dismissal_time, reason=reason
    )


class TestBaseDismissal:
    def test_regular_day_uses_default(self, child):
        assert resolve_effective_pickup_time(child, MONDAY) == utc(20)  # 3pm CDT

    def test_early_dismissal_weekday_override(self, child):
        assert resolve_effective_pickup_time(child, WEDNESDAY) == utc(
            18, 30, WEDNESDAY
        )  # 1:30pm CDT

    def test_weekend_is_none(self, child):
        assert resolve_effective_pickup_time(child, SATURDAY) is None

    def test_no_school_child_is_none(self, child):
        child.school = None
        assert resolve_effective_pickup_time(child, MONDAY) is None


class TestCalendarExceptions:
    def test_exception_overrides_default(self, child):
        add_exception(child, MONDAY, datetime.time(12, 0), "Early release")
        assert resolve_effective_pickup_time(child, MONDAY) == utc(17)  # noon CDT

    def test_exception_beats_early_dismissal_override(self, child):
        add_exception(child, WEDNESDAY, datetime.time(11, 0))
        assert resolve_effective_pickup_time(child, WEDNESDAY) == utc(
            16, 0, WEDNESDAY
        )

    def test_holiday_no_activity_is_none(self, child):
        add_exception(child, MONDAY, None, "Holiday")
        assert resolve_effective_pickup_time(child, MONDAY) is None


class TestActivities:
    def test_later_activity_extends_pickup(self, child):
        add_activity(child, day=0, end=datetime.time(17, 0))
        assert resolve_effective_pickup_time(child, MONDAY) == utc(22)  # 5pm CDT

    def test_earlier_activity_ignored(self, child):
        add_activity(child, day=0, end=datetime.time(14, 0), start=datetime.time(13, 0))
        assert resolve_effective_pickup_time(child, MONDAY) == utc(20)

    def test_activity_on_other_day_ignored(self, child):
        add_activity(child, day=3, end=datetime.time(17, 0))  # Thursday
        assert resolve_effective_pickup_time(child, MONDAY) == utc(20)

    def test_latest_of_multiple_activities_wins(self, child):
        add_activity(child, day=0, end=datetime.time(16, 30))
        add_activity(child, day=0, end=datetime.time(17, 45))
        assert resolve_effective_pickup_time(child, MONDAY) == utc(22, 45)

    def test_activity_on_holiday_stands_alone(self, child):
        add_exception(child, MONDAY, None, "Holiday")
        add_activity(child, day=0, end=datetime.time(12, 0), start=datetime.time(10, 0))
        assert resolve_effective_pickup_time(child, MONDAY) == utc(17)

    def test_activity_with_early_dismissal(self, child):
        add_activity(child, day=2, end=datetime.time(15, 0), start=datetime.time(13, 45))
        assert resolve_effective_pickup_time(child, WEDNESDAY) == utc(
            20, 0, WEDNESDAY
        )
