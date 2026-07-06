"""Rotation engine correctness (SYSTEMS-DEEP-DIVE.md §3).

Anchor Monday 2026-07-06. Weekdays-only cycles unless stated.
"""

import datetime

import pytest

from carpool.models import CarpoolAssignment, CarpoolRotationRule
from carpool.services import generate_assignments
from carpool.tests.conftest import make_rule
from schools.models import SchoolCalendarException

pytestmark = pytest.mark.django_db

MON = datetime.date(2026, 7, 6)


def day(offset):
    return MON + datetime.timedelta(days=offset)


def drivers(group, date_from, date_to):
    return [
        (a.date, a.driver_family.name)
        for a in group.assignments.filter(
            date__range=(date_from, date_to)
        ).order_by("date")
    ]


class TestRoundRobin:
    def test_two_week_cycle(self, group, actors):
        _, families = actors
        rule = make_rule(group, [families["a"], families["b"], families["c"]])
        created = generate_assignments(rule, MON, day(11))  # Mon–Fri x2

        assert len(created) == 10
        names = [a.driver_family.name for a in created]
        assert names == [
            "Family A", "Family B", "Family C", "Family A", "Family B",
            "Family C", "Family A", "Family B", "Family C", "Family A",
        ]
        assert all(a.status == "suggested" for a in created)
        assert all(a.is_auto_suggested for a in created)

    def test_cycle_days_respected(self, group, actors):
        _, families = actors
        rule = make_rule(
            group, [families["a"], families["b"]], cycle_days=(0, 2)
        )  # Mon + Wed only
        created = generate_assignments(rule, MON, day(6))
        assert [a.date for a in created] == [MON, day(2)]

    def test_weekends_never_assigned(self, group, actors):
        _, families = actors
        rule = make_rule(group, [families["a"]])
        created = generate_assignments(rule, MON, day(13))
        assert all(a.date.weekday() < 5 for a in created)

    def test_manual_only_generates_nothing(self, group, actors):
        _, families = actors
        rule = make_rule(
            group, [families["a"]], rotation_type="manual_only"
        )
        assert generate_assignments(rule, MON, day(11)) == []


class TestWeighted:
    def test_weight_by_repetition(self, group, actors):
        """Weights [2,1,1] over [A,B,C] → cycle A,A,B,C."""
        _, families = actors
        rule = make_rule(
            group,
            [families["a"], families["b"], families["c"]],
            rotation_type="weighted",
            weights=[2, 1, 1],
        )
        created = generate_assignments(rule, MON, day(11))  # 10 slots
        names = [a.driver_family.name for a in created]
        assert names == [
            "Family A", "Family A", "Family B", "Family C",
            "Family A", "Family A", "Family B", "Family C",
            "Family A", "Family A",
        ]

    def test_round_robin_ignores_weights(self, group, actors):
        _, families = actors
        rule = make_rule(
            group,
            [families["a"], families["b"]],
            rotation_type="round_robin",
            weights=[5, 1],
        )
        created = generate_assignments(rule, MON, day(3))
        names = [a.driver_family.name for a in created]
        assert names == ["Family A", "Family B", "Family A", "Family B"]


class TestNeverOverwrite:
    def test_existing_assignment_untouched_and_consumes_slot(
        self, group, actors
    ):
        """A pre-existing manual row keeps its driver AND its slot: the
        sequence around it is exactly what it would have been anyway."""
        _, families = actors
        rule = make_rule(group, [families["a"], families["b"], families["c"]])
        # Manually give Wednesday (slot 2, would be C) to B
        manual = CarpoolAssignment.objects.create(
            carpool_group=group,
            date=day(2),
            driver_family=families["b"],
            status="confirmed",
        )
        created = generate_assignments(rule, MON, day(4))

        assert len(created) == 4  # Wed skipped
        manual.refresh_from_db()
        assert manual.driver_family == families["b"]
        assert manual.status == "confirmed"
        assert drivers(group, MON, day(4)) == [
            (MON, "Family A"),
            (day(1), "Family B"),
            (day(2), "Family B"),   # manual override kept
            (day(3), "Family A"),   # slot counting unaffected: Thu = slot 3
            (day(4), "Family B"),
        ]

    def test_regeneration_is_idempotent(self, group, actors):
        _, families = actors
        rule = make_rule(group, [families["a"], families["b"]])
        first = generate_assignments(rule, MON, day(11))
        second = generate_assignments(rule, MON, day(11))
        assert len(first) == 10
        assert second == []
        assert group.assignments.count() == 10


class TestSlotAnchoring:
    def test_later_window_continues_sequence(self, group, actors):
        """Generating week 2 alone must produce the same drivers as
        generating weeks 1–2 together (slots counted from start_date)."""
        _, families = actors
        rule = make_rule(group, [families["a"], families["b"], families["c"]])
        created = generate_assignments(rule, day(7), day(11))  # week 2 only

        # Week 1 had 5 slots (0–4), so week 2 starts at slot 5 → C,A,B,C,A
        names = [a.driver_family.name for a in created]
        assert names == [
            "Family C", "Family A", "Family B", "Family C", "Family A",
        ]

    def test_holiday_excluded_and_shifts_slots(self, group, actors):
        """A no-school exception day gets no assignment and consumes no
        slot — the next in-session day gets the driver the holiday would
        have had."""
        _, families = actors
        rule = make_rule(group, [families["a"], families["b"], families["c"]])
        SchoolCalendarException.objects.create(
            school=group.school, date=day(1), dismissal_time=None, reason="Holiday"
        )
        created = generate_assignments(rule, MON, day(4))
        assert [(a.date, a.driver_family.name) for a in created] == [
            (MON, "Family A"),
            (day(2), "Family B"),  # Tue holiday skipped, B slides to Wed
            (day(3), "Family C"),
            (day(4), "Family A"),
        ]

    def test_early_dismissal_exception_still_in_session(self, group, actors):
        _, families = actors
        rule = make_rule(group, [families["a"], families["b"]])
        SchoolCalendarException.objects.create(
            school=group.school,
            date=MON,
            dismissal_time=datetime.time(12, 0),
            reason="Early release",
        )
        created = generate_assignments(rule, MON, day(1))
        assert [a.date for a in created] == [MON, day(1)]


class TestRotationRuleChoices:
    def test_rotation_types_match_schema(self):
        assert set(CarpoolRotationRule.RotationType.values) == {
            "round_robin",
            "weighted",
            "manual_only",
        }
