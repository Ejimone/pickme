from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import exceptions, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from carpool.models import (
    CarpoolAssignment,
    CarpoolGroup,
    CarpoolGroupInvite,
    CarpoolGroupMember,
    CarpoolSwapRequest,
)
from carpool.serializers import (
    AssignmentSerializer,
    CarpoolGroupInviteSerializer,
    CarpoolGroupMemberSerializer,
    CarpoolGroupSerializer,
    CarpoolInviteAcceptSerializer,
    CarpoolInviteCreateSerializer,
    GenerateAssignmentsSerializer,
    JoinGroupSerializer,
    RotationRuleSerializer,
    SwapRequestSerializer,
    SwapRespondSerializer,
)
from carpool.services import generate_assignments
from core.permissions import IsCarpoolGroupAdmin, IsCarpoolGroupMember


class CarpoolGroupViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CarpoolGroupSerializer
    permission_classes = [IsCarpoolGroupMember]

    def get_queryset(self):
        return (
            CarpoolGroup.objects.filter(
                members__family__members__user=self.request.user
            )
            .distinct()
            .select_related("school")
            .order_by("created_at")
        )

    def perform_create(self, serializer):
        family = serializer.validated_data.pop("family")
        group = serializer.save(created_by=self.request.user)
        CarpoolGroupMember.objects.create(
            carpool_group=group,
            family=family,
            role=CarpoolGroupMember.Role.ADMIN,
        )

    def _require_admin(self, group):
        is_admin = group.members.filter(
            family__members__user=self.request.user,
            role=CarpoolGroupMember.Role.ADMIN,
        ).exists()
        if not is_admin:
            raise exceptions.PermissionDenied(
                "You must be a carpool group admin to do this."
            )

    @action(detail=False, methods=["post"])
    def join(self, request):
        serializer = JoinGroupSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            group = CarpoolGroup.objects.get(
                invite_code=serializer.validated_data["invite_code"]
            )
        except CarpoolGroup.DoesNotExist:
            raise exceptions.NotFound("Invalid invite code.")
        member, created = CarpoolGroupMember.objects.get_or_create(
            carpool_group=group,
            family=serializer.validated_data["family"],
            defaults={"role": CarpoolGroupMember.Role.MEMBER},
        )
        return Response(
            {
                "group": CarpoolGroupSerializer(group).data,
                "member": CarpoolGroupMemberSerializer(member).data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        group = self.get_object()
        page = self.paginate_queryset(
            group.members.select_related("family").order_by("joined_at")
        )
        serializer = CarpoolGroupMemberSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"members/(?P<member_id>[^/.]+)",
    )
    def remove_member(self, request, pk=None, member_id=None):
        group = self.get_object()
        self._require_admin(group)
        try:
            member = group.members.get(pk=member_id)
        except CarpoolGroupMember.DoesNotExist:
            raise exceptions.NotFound("Group member not found.")
        if (
            member.role == CarpoolGroupMember.Role.ADMIN
            and group.members.filter(role=CarpoolGroupMember.Role.ADMIN).count() == 1
        ):
            raise exceptions.ValidationError(
                {"member": ["Cannot remove the group's only admin."]}
            )
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """POST /carpool-groups/{id}/invite/ — admin emails a parent an invite.

        Mirrors the family-invite flow: the email carries both the group's
        invite_code (to type into "Join with a code") and a deep link for
        one-tap accept. Re-inviting a still-pending email resends, not
        duplicates (get_or_create on the pending row).
        """
        group = self.get_object()
        self._require_admin(group)
        serializer = CarpoolInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()

        invite, _ = CarpoolGroupInvite.objects.get_or_create(
            group=group,
            email=email,
            status=CarpoolGroupInvite.Status.PENDING,
            defaults={"invited_by": request.user},
        )
        inviter = request.user.full_name or request.user.email
        send_mail(
            subject=f"You're invited to join {group.name}",
            message=(
                f"{inviter} invited you to join the carpool group "
                f'"{group.name}". Open the app and either tap this link:\n\n'
                f"pickme://carpool/accept?token={invite.token}\n\n"
                f'or use "Join with a code" and enter: {group.invite_code}'
            ),
            from_email=None,
            recipient_list=[email],
            fail_silently=True,
        )
        return Response(
            CarpoolGroupInviteSerializer(invite).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        """POST /carpool-groups/{id}/leave/ — remove the caller's family.

        Last-admin handling: if the leaving family is the only admin and other
        members remain, the oldest remaining member is auto-promoted to admin
        (chosen over a 409 block for smoother mobile UX — see DECISIONS.md).
        """
        group = self.get_object()
        memberships = list(
            group.members.filter(family__members__user=request.user)
        )
        if not memberships:
            raise exceptions.PermissionDenied(
                "You are not a member of this group."
            )

        leaving_ids = [m.id for m in memberships]
        leaving_is_admin = any(
            m.role == CarpoolGroupMember.Role.ADMIN for m in memberships
        )
        with transaction.atomic():
            remaining = group.members.exclude(id__in=leaving_ids)
            has_other_admin = remaining.filter(
                role=CarpoolGroupMember.Role.ADMIN
            ).exists()
            if leaving_is_admin and remaining.exists() and not has_other_admin:
                heir = remaining.order_by("joined_at").first()
                heir.role = CarpoolGroupMember.Role.ADMIN
                heir.save(update_fields=["role"])
            group.members.filter(id__in=leaving_ids).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "put"], url_path="rotation-rule")
    def rotation_rule(self, request, pk=None):
        group = self.get_object()
        if request.method == "PUT":
            self._require_admin(group)
            serializer = RotationRuleSerializer(
                data=request.data,
                context={"request": request, "carpool_group": group},
            )
            serializer.is_valid(raise_exception=True)
            with transaction.atomic():
                rule = serializer.save_for_group(group)
            return Response(RotationRuleSerializer(rule).data)

        rule = getattr(group, "rotation_rule", None)
        if rule is None:
            raise exceptions.NotFound("No rotation rule configured.")
        return Response(RotationRuleSerializer(rule).data)

    @action(detail=True, methods=["get"])
    def assignments(self, request, pk=None):
        group = self.get_object()
        qs = group.assignments.select_related("driver_family").order_by("date")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        page = self.paginate_queryset(qs)
        serializer = AssignmentSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["post"], url_path="assignments/generate")
    def generate(self, request, pk=None):
        group = self.get_object()
        rule = getattr(group, "rotation_rule", None)
        if rule is None:
            raise exceptions.ValidationError(
                {"rotation_rule": ["Configure a rotation rule first."]}
            )
        serializer = GenerateAssignmentsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            created = generate_assignments(
                rule,
                serializer.validated_data["date_from"],
                serializer.validated_data["date_to"],
            )
        return Response(
            {"created": AssignmentSerializer(created, many=True).data},
            status=status.HTTP_201_CREATED,
        )


class AssignmentViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AssignmentSerializer
    permission_classes = [IsCarpoolGroupMember]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        return CarpoolAssignment.objects.filter(
            carpool_group__members__family__members__user=self.request.user
        ).distinct().select_related("carpool_group", "driver_family")

    def _user_in_family(self, family):
        return family.members.filter(user=self.request.user).exists()

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        assignment = self.get_object()
        if not self._user_in_family(assignment.driver_family):
            raise exceptions.PermissionDenied(
                "Only the driver family can confirm this assignment."
            )
        if assignment.status not in (
            CarpoolAssignment.Status.SUGGESTED,
            CarpoolAssignment.Status.CONFIRMED,
        ):
            raise exceptions.ValidationError(
                {"status": [f"Cannot confirm a {assignment.status} assignment."]}
            )
        assignment.status = CarpoolAssignment.Status.CONFIRMED
        assignment.driver_user = request.user
        assignment.save(update_fields=["status", "driver_user", "updated_at"])
        return Response(AssignmentSerializer(assignment).data)

    @action(detail=True, methods=["post"], url_path="swap-requests")
    def swap_requests(self, request, pk=None):
        assignment = self.get_object()
        if not self._user_in_family(assignment.driver_family):
            raise exceptions.PermissionDenied(
                "Only the assigned driver family can request a swap."
            )
        serializer = SwapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_family = serializer.validated_data["target_family"]

        if target_family == assignment.driver_family:
            raise exceptions.ValidationError(
                {"target_family": ["Cannot request a swap with yourself."]}
            )
        if not assignment.carpool_group.members.filter(
            family=target_family
        ).exists():
            raise exceptions.ValidationError(
                {"target_family": ["Family is not a member of this group."]}
            )
        if assignment.swap_requests.filter(
            status=CarpoolSwapRequest.Status.PENDING
        ).exists():
            raise exceptions.ValidationError(
                {"assignment": ["A swap request is already pending."]}
            )

        with transaction.atomic():
            swap = serializer.save(
                assignment=assignment, requested_by=request.user
            )
            assignment.status = CarpoolAssignment.Status.SWAP_PENDING
            assignment.save(update_fields=["status", "updated_at"])
        return Response(
            SwapRequestSerializer(swap).data, status=status.HTTP_201_CREATED
        )


class SwapRequestViewSet(viewsets.GenericViewSet):
    serializer_class = SwapRequestSerializer
    permission_classes = [IsCarpoolGroupMember]

    def get_queryset(self):
        return CarpoolSwapRequest.objects.filter(
            assignment__carpool_group__members__family__members__user=self.request.user
        ).distinct().select_related("assignment", "target_family")

    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        swap = self.get_object()
        if not swap.target_family.members.filter(user=request.user).exists():
            raise exceptions.PermissionDenied(
                "Only the target family can respond to this swap request."
            )
        if swap.status != CarpoolSwapRequest.Status.PENDING:
            raise exceptions.ValidationError(
                {"status": [f"Swap request is already {swap.status}."]}
            )
        serializer = SwapRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        accept = serializer.validated_data["action"] == "accept"

        assignment = swap.assignment
        with transaction.atomic():
            if accept:
                swap.status = CarpoolSwapRequest.Status.ACCEPTED
                # Point-in-time exception: only this assignment changes;
                # the rotation order is never re-anchored.
                assignment.driver_family = swap.target_family
                assignment.driver_user = request.user
                assignment.status = CarpoolAssignment.Status.CONFIRMED
                assignment.save(
                    update_fields=[
                        "driver_family",
                        "driver_user",
                        "status",
                        "updated_at",
                    ]
                )
            else:
                swap.status = CarpoolSwapRequest.Status.REJECTED
                assignment.status = (
                    CarpoolAssignment.Status.CONFIRMED
                    if assignment.driver_user_id
                    else CarpoolAssignment.Status.SUGGESTED
                )
                assignment.save(update_fields=["status", "updated_at"])
            swap.resolved_at = timezone.now()
            swap.save(update_fields=["status", "resolved_at"])

        return Response(
            {
                "swap_request": SwapRequestSerializer(swap).data,
                "assignment": AssignmentSerializer(assignment).data,
            }
        )


class CarpoolInviteAcceptView(APIView):
    """POST /carpool-group-invites/accept/ {"token","family"} — join by token.

    Mirrors families.InviteAcceptView: validates a pending token, adds the
    caller's family to the group as a member (idempotent), marks the invite
    accepted.
    """

    @extend_schema(
        request=CarpoolInviteAcceptSerializer, responses=OpenApiTypes.OBJECT
    )
    def post(self, request):
        serializer = CarpoolInviteAcceptSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        try:
            invite = CarpoolGroupInvite.objects.select_related("group").get(
                token=serializer.validated_data["token"],
                status=CarpoolGroupInvite.Status.PENDING,
            )
        except CarpoolGroupInvite.DoesNotExist:
            raise exceptions.NotFound("Invite not found or no longer valid.")

        member, created = CarpoolGroupMember.objects.get_or_create(
            carpool_group=invite.group,
            family=serializer.validated_data["family"],
            defaults={"role": CarpoolGroupMember.Role.MEMBER},
        )
        invite.status = CarpoolGroupInvite.Status.ACCEPTED
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["status", "accepted_at"])
        return Response(
            {
                "group": CarpoolGroupSerializer(invite.group).data,
                "member": CarpoolGroupMemberSerializer(member).data,
            },
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED,
        )
