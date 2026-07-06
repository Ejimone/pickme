"""Effective pickup time resolution ("Today" logic).

Precedence for a child's pickup time on a given date:

1. School calendar exception for that date, when present:
   - `dismissal_time = None` means no school (holiday/snow day)
   - otherwise it overrides the regular dismissal time
2. Regular schedule: `early_dismissal_days` weekday override
   (JSON `{"2": "13:30"}`, 0=Monday) → else `default_dismissal_time`
3. The later of the base dismissal and any of the child's activities that
   day — practice ending at 5pm pushes pickup to 5pm. On a no-school day
   an activity alone still yields a pickup time (per DECISIONS.md).

All comparisons happen in the school's local timezone; the result is a
UTC-aware datetime (DB convention), or None when there is nothing to pick
up (no school and no activity, or child not enrolled anywhere).
"""

import datetime
from zoneinfo import ZoneInfo


def resolve_effective_pickup_time(child, date):
    """Return the effective pickup datetime (UTC) for `child` on `date`."""
    school = child.school
    if school is None:
        return None

    base_time = _base_dismissal_time(school, date)
    activity_end = _latest_activity_end(child, date)

    candidates = [t for t in (base_time, activity_end) if t is not None]
    if not candidates:
        return None

    local = datetime.datetime.combine(
        date, max(candidates), tzinfo=ZoneInfo(school.timezone)
    )
    return local.astimezone(datetime.timezone.utc)


def _base_dismissal_time(school, date):
    """School dismissal time for `date`, or None if no school that day."""
    exception = school.calendar_exceptions.filter(date=date).first()
    if exception is not None:
        return exception.dismissal_time  # may be None = no school

    weekday = date.weekday()
    if weekday >= 5:  # weekend — no regular school day
        return None

    early_days = school.early_dismissal_days or {}
    override = early_days.get(str(weekday))
    if override:
        hour, minute = map(int, override.split(":"))
        return datetime.time(hour, minute)
    return school.default_dismissal_time


def _latest_activity_end(child, date):
    end_times = child.activities.filter(day_of_week=date.weekday()).values_list(
        "end_time", flat=True
    )
    return max(end_times, default=None)
