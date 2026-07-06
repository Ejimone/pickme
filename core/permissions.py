"""Membership-scoped permission classes shared across apps.

Family/carpool models land in Stages 1 and 3, so these resolve models
lazily via the app registry — importing this module never requires them.

Views using these must either expose a `family`/`carpool_group` URL kwarg
or return objects with a resolvable family/carpool group (see the
`_family_id_of` / `_group_id_of` helpers).
"""

from django.apps import apps
from rest_framework.permissions import BasePermission


def _family_id_of(obj):
    if obj.__class__.__name__ == "Family":
        return obj.pk
    if hasattr(obj, "family_id"):
        return obj.family_id
    return None


def _group_id_of(obj):
    if obj.__class__.__name__ == "CarpoolGroup":
        return obj.pk
    if hasattr(obj, "carpool_group_id"):
        return obj.carpool_group_id
    return None


class IsFamilyMember(BasePermission):
    """User belongs to the family that owns the object."""

    message = "You are not a member of this family."

    def has_permission(self, request, view):
        family_id = view.kwargs.get("family_id") or view.kwargs.get("family_pk")
        if family_id is None:
            return True  # defer to object-level check
        return self._is_member(request.user, family_id)

    def has_object_permission(self, request, view, obj):
        family_id = _family_id_of(obj)
        return family_id is not None and self._is_member(request.user, family_id)

    @staticmethod
    def _is_member(user, family_id):
        FamilyMember = apps.get_model("families", "FamilyMember")
        return FamilyMember.objects.filter(family_id=family_id, user=user).exists()


class IsCarpoolGroupMember(BasePermission):
    """One of the user's families belongs to the carpool group."""

    message = "Your family is not a member of this carpool group."
    required_roles = None  # None = any role

    def has_permission(self, request, view):
        group_id = view.kwargs.get("carpool_group_id") or view.kwargs.get(
            "carpool_group_pk"
        )
        if group_id is None:
            return True  # defer to object-level check
        return self._is_member(request.user, group_id)

    def has_object_permission(self, request, view, obj):
        group_id = _group_id_of(obj)
        return group_id is not None and self._is_member(request.user, group_id)

    def _is_member(self, user, group_id):
        CarpoolGroupMember = apps.get_model("carpool", "CarpoolGroupMember")
        qs = CarpoolGroupMember.objects.filter(
            carpool_group_id=group_id, family__members__user=user
        )
        if self.required_roles:
            qs = qs.filter(role__in=self.required_roles)
        return qs.exists()


class IsCarpoolGroupAdmin(IsCarpoolGroupMember):
    message = "You must be a carpool group admin to do this."
    required_roles = ("admin",)
