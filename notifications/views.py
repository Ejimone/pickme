from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from notifications.models import DeviceToken, Notification, NotificationPreference
from notifications.serializers import (
    DeviceTokenSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
)


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """`GET /notifications/` (own, `?is_read=` filter) and
    `POST /notifications/{id}/read/`."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Notification.objects.filter(user=self.request.user)
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            queryset = queryset.filter(
                is_read=is_read.lower() in ("1", "true", "yes")
            )
        return queryset

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        return Response(NotificationSerializer(notification).data)


class NotificationPreferenceViewSet(
    mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """`GET /notification-preferences/` lists a row for every type (defaults
    for any the user hasn't customized). `PATCH /notification-preferences/
    {type}/` updates channel toggles, materializing the row on first touch."""

    serializer_class = NotificationPreferenceSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "notification_type"
    lookup_value_regex = "[a-z_]+"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return NotificationPreference.objects.filter(user=self.request.user)

    def list(self, request):
        existing = {
            pref.notification_type: pref for pref in self.get_queryset()
        }
        rows = []
        for value, _label in Notification.Type.choices:
            pref = existing.get(value) or NotificationPreference(
                user=request.user, notification_type=value
            )
            rows.append(NotificationPreferenceSerializer(pref).data)
        return Response(rows)

    def get_object(self):
        notification_type = self.kwargs[self.lookup_field]
        if notification_type not in Notification.Type.values:
            raise NotFound("Unknown notification type.")
        pref, _ = NotificationPreference.objects.get_or_create(
            user=self.request.user, notification_type=notification_type
        )
        return pref


class DeviceTokenViewSet(
    mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """`POST /device-tokens/` (register, idempotent per token) and
    `DELETE /device-tokens/{id}/` (logout)."""

    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return DeviceToken.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Re-registering a token (e.g. after reinstall) rebinds it to this user
        # rather than 409-ing on the unique constraint.
        token, _ = DeviceToken.objects.update_or_create(
            token=serializer.validated_data["token"],
            defaults={
                "user": request.user,
                "platform": serializer.validated_data["platform"],
            },
        )
        return Response(
            DeviceTokenSerializer(token).data, status=status.HTTP_201_CREATED
        )
