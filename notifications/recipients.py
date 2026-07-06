"""Who receives a notification for a given trigger context.

Each helper returns a de-duplicated list of `User`s. Kept out of `signals.py`
so the receivers stay thin (working rule #7) and the membership queries are
testable on their own.
"""

from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


def family_recipients(family):
    """Every member of a family."""
    return list(
        User.objects.filter(family_memberships__family=family).distinct()
    )


def school_recipients(school):
    """Members of any family with an active child at this school."""
    return list(
        User.objects.filter(
            family_memberships__family__children__school=school,
            family_memberships__family__children__is_active=True,
        ).distinct()
    )


def trip_stop_recipients(stop):
    """Members of the families whose children are at this trip stop."""
    return list(
        User.objects.filter(
            family_memberships__family__children__trip_stop_entries__trip_stop=stop
        ).distinct()
    )


def thread_recipients(thread):
    """Everyone party to a chat thread: the carpool group's member families,
    plus (for a trip thread) the driver and the families with a child at a
    stop. Mirrors `chat.services.threads_visible_to`, inverted onto users."""
    criteria = Q()
    if thread.carpool_group_id:
        criteria |= Q(
            family_memberships__family__carpool_memberships__carpool_group=(
                thread.carpool_group_id
            )
        )
    if thread.trip_id:
        criteria |= (
            Q(trips=thread.trip_id)  # the driver
            | Q(
                family_memberships__family__children__trip_stop_entries__trip_stop__trip=(
                    thread.trip_id
                )
            )
        )
    if not criteria:
        return []
    return list(User.objects.filter(criteria).distinct())
