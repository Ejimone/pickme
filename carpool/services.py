"""Rotation engine (SYSTEMS-DEEP-DIVE.md §3), implemented as specified.

Core rule: generation only fills gaps — any date that already has a
CarpoolAssignment (manual, swapped, or previously generated) is left
untouched, and still consumes its slot in the sequence. That makes
generation idempotent and safe to re-run on demand or on a schedule.

Swaps and manual edits are point-in-time exceptions on single assignment
rows; they never re-anchor the deterministic sequence.
"""

import datetime

from carpool.models import (
    CarpoolAssignment,
    CarpoolRotationRule,
)


def generate_assignments(rule, date_from, date_to):
    """Fill suggested CarpoolAssignments for [date_from, date_to].

    Returns the list of created assignments (existing dates are skipped).
    """
    if rule.rotation_type == CarpoolRotationRule.RotationType.MANUAL_ONLY:
        return []

    expanded_sequence = _expanded_sequence(rule)
    if not expanded_sequence:
        return []

    school = rule.carpool_group.school
    applicable_dates = _applicable_dates(rule, school, date_from, date_to)

    # Where in the cycle does this window start? Count applicable dates
    # from the rule's anchor up to (not including) the window.
    slot_number = len(_applicable_dates(rule, school, rule.start_date, date_from - datetime.timedelta(days=1)))

    existing_dates = set(
        CarpoolAssignment.objects.filter(
            carpool_group=rule.carpool_group,
            date__range=(date_from, date_to),
        ).values_list("date", flat=True)
    )

    created = []
    for date in applicable_dates:
        if date in existing_dates:
            slot_number += 1
            continue  # never overwrite

        family = expanded_sequence[slot_number % len(expanded_sequence)]
        created.append(
            CarpoolAssignment.objects.create(
                carpool_group=rule.carpool_group,
                date=date,
                driver_family=family,
                status=CarpoolAssignment.Status.SUGGESTED,
                is_auto_suggested=True,
            )
        )
        slot_number += 1

    return created


def _expanded_sequence(rule):
    """Weight-by-repetition: weights [2,1,1] over [A,B,C] → [A,A,B,C]."""
    sequence = []
    entries = rule.order_entries.select_related("family").order_by("position")
    weighted = rule.rotation_type == CarpoolRotationRule.RotationType.WEIGHTED
    for entry in entries:
        repeats = entry.weight if weighted else 1
        sequence.extend([entry.family] * max(repeats, 0))
    return sequence


def _applicable_dates(rule, school, date_from, date_to):
    """Dates in range on a cycle weekday with school in session."""
    if date_from > date_to:
        return []
    cycle_days = set(rule.cycle_days)
    closed_dates = set(
        school.calendar_exceptions.filter(
            date__range=(date_from, date_to), dismissal_time__isnull=True
        ).values_list("date", flat=True)
    )
    days = (date_to - date_from).days + 1
    return [
        d
        for d in (date_from + datetime.timedelta(days=i) for i in range(days))
        if d.weekday() in cycle_days and d not in closed_dates
    ]
