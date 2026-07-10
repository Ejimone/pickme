from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import exceptions, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsFamilyMember
from families.models import Activity, Child, Family, FamilyInvite, FamilyMember
from families.serializers import (
    ActivitySerializer,
    ChildSerializer,
    FamilyInviteSerializer,
    FamilyMemberSerializer,
    FamilySerializer,
    InviteAcceptSerializer,
)


class FamilyViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = FamilySerializer
    permission_classes = [IsFamilyMember]

    def get_queryset(self):
        return (
            Family.objects.filter(members__user=self.request.user)
            .annotate(member_count=Count("members"))
            .order_by("created_at")
        )

    def perform_create(self, serializer):
        family = serializer.save(created_by=self.request.user)
        FamilyMember.objects.create(
            family=family, user=self.request.user, role=FamilyMember.Role.OWNER
        )

    def perform_update(self, serializer):
        self._require_owner(serializer.instance)
        serializer.save()

    def _require_owner(self, family):
        is_owner = family.members.filter(
            user=self.request.user, role=FamilyMember.Role.OWNER
        ).exists()
        if not is_owner:
            raise exceptions.PermissionDenied(
                "Only the family owner can do this."
            )

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        family = self.get_object()
        page = self.paginate_queryset(
            family.members.select_related("user").order_by("joined_at")
        )
        serializer = FamilyMemberSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["post"], url_path="members/invite")
    def invite(self, request, pk=None):
        family = self.get_object()
        serializer = FamilyInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()

        if family.members.filter(user__email__iexact=email).exists():
            raise exceptions.ValidationError(
                {"email": ["This user is already a family member."]}
            )
        if family.invites.filter(
            email__iexact=email, status=FamilyInvite.Status.PENDING
        ).exists():
            raise exceptions.ValidationError(
                {"email": ["An invite for this email is already pending."]}
            )

        invite = FamilyInvite.objects.create(
            family=family, email=email, invited_by=request.user
        )
        send_mail(
            subject=f"You're invited to join {family.name}",
            message=(
                f"{request.user.full_name or request.user.email} invited you "
                f"to join {family.name}. Open the app and redeem invite "
                f"token: {invite.token}"
            ),
            from_email=None,
            recipient_list=[email],
            fail_silently=True,
        )
        return Response(
            FamilyInviteSerializer(invite).data, status=status.HTTP_201_CREATED
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"members/(?P<member_id>[^/.]+)",
    )
    def remove_member(self, request, pk=None, member_id=None):
        family = self.get_object()
        self._require_owner(family)
        try:
            member = family.members.get(pk=member_id)
        except FamilyMember.DoesNotExist:
            raise exceptions.NotFound("Family member not found.")
        if member.role == FamilyMember.Role.OWNER:
            raise exceptions.ValidationError(
                {"member": ["The family owner cannot be removed."]}
            )
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteAcceptView(APIView):
    """POST /family-invites/accept/ {"token": "..."} — joins the family."""

    @extend_schema(request=InviteAcceptSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invite = FamilyInvite.objects.select_related("family").get(
                token=serializer.validated_data["token"],
                status=FamilyInvite.Status.PENDING,
            )
        except FamilyInvite.DoesNotExist:
            raise exceptions.NotFound("Invite not found or no longer valid.")

        member, created = FamilyMember.objects.get_or_create(
            family=invite.family,
            user=request.user,
            defaults={"role": FamilyMember.Role.MEMBER},
        )
        invite.status = FamilyInvite.Status.ACCEPTED
        invite.responded_at = timezone.now()
        invite.save(update_fields=["status", "responded_at"])
        return Response(
            {
                "family": FamilySerializer(invite.family).data,
                "member": FamilyMemberSerializer(member).data,
            },
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED,
        )


class ChildViewSet(viewsets.ModelViewSet):
    serializer_class = ChildSerializer
    permission_classes = [IsFamilyMember]

    def get_queryset(self):
        qs = (
            Child.objects.filter(
                family__members__user=self.request.user, is_active=True
            )
            .select_related("school")
            .order_by("created_at")
        )
        family = self.request.query_params.get("family")
        school = self.request.query_params.get("school")
        if family:
            qs = qs.filter(family_id=family)
        if school:
            qs = qs.filter(school_id=school)
        return qs

    def perform_destroy(self, instance):
        # Soft-delete: pickup history keeps referencing the row.
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    # Avatars are normalized to a small, square, face-cropped JPEG so stored
    # assets are uniform and cheap; Cloudinary decodes the source (HEIC/HEIF/
    # PNG/WebP/JPEG) natively before applying this.
    AVATAR_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
    AVATAR_TRANSFORMATION = "c_fill,g_face,h_512,w_512,q_auto"

    @action(
        detail=True,
        methods=["post"],
        url_path="photo",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def photo(self, request, pk=None):
        """POST /children/{id}/photo/ — set the child's avatar.

        Two content types are accepted:

        * ``multipart/form-data`` with a single file field named ``file`` — the
          raw image (HEIC/HEIF/PNG/WebP/JPEG) is proxied to Cloudinary, which
          decodes and normalizes it; we store the returned secure URL.
        * ``application/json`` ``{"photo_url": "https://…"}`` — an already-hosted
          image (e.g. after a client-side signed upload via /media/signature/);
          stored directly, no re-upload.

        Returns the full updated Child (same shape as GET /children/{id}/).
        """
        from core.cloudinary import get_media_client

        child = self.get_object()
        upload = request.FILES.get("file")

        if upload is not None:
            content_type = (upload.content_type or "").lower()
            if not content_type.startswith("image/"):
                raise exceptions.ValidationError(
                    {"file": ["Unsupported file type."]}
                )
            if upload.size > self.AVATAR_MAX_BYTES:
                raise exceptions.ValidationError(
                    {"file": ["Image is too large (max 10 MB)."]}
                )
            child.photo_url = get_media_client().upload(
                upload,
                folder=settings.CLOUDINARY_AVATAR_FOLDER,
                resource_type="image",
                overwrite=True,
                transformation=self.AVATAR_TRANSFORMATION,
                format="jpg",
            )
        elif request.data.get("photo_url"):
            photo_url = str(request.data["photo_url"]).strip()
            if not photo_url.lower().startswith("https://"):
                raise exceptions.ValidationError(
                    {"photo_url": ["Must be an https URL."]}
                )
            child.photo_url = photo_url
        else:
            raise exceptions.ValidationError(
                {"file": ["No image provided."]}
            )

        child.save(update_fields=["photo_url"])
        return Response(ChildSerializer(child).data)

    @action(detail=True, methods=["get", "post"], url_path="activities")
    def activities(self, request, pk=None):
        """GET/POST /children/{child_id}/activities/"""
        child = self.get_object()
        if request.method == "POST":
            serializer = ActivitySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(child=child)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        page = self.paginate_queryset(
            child.activities.order_by("day_of_week", "start_time")
        )
        serializer = ActivitySerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class ActivityViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Flat routes per API-DESIGN.md: PATCH/DELETE /activities/{id}/."""

    serializer_class = ActivitySerializer

    def get_queryset(self):
        return Activity.objects.filter(
            child__family__members__user=self.request.user,
            child__is_active=True,
        ).select_related("child")
