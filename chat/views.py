from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from chat.models import ChatMessage, ChatThread
from chat.permissions import IsThreadParticipant
from chat.serializers import (
    ChatMessageCreateSerializer,
    ChatMessageSerializer,
    ChatThreadSerializer,
    MarkReadSerializer,
)
from chat.services import mark_read, post_message, threads_visible_to
from core.pagination import TimeOrderedCursorPagination


class ChatThreadViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ChatThreadSerializer
    permission_classes = [IsAuthenticated, IsThreadParticipant]

    def get_queryset(self):
        return (
            ChatThread.objects.filter(threads_visible_to(self.request.user))
            .distinct()
            .order_by("-created_at")
        )

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        thread = self.get_object()
        if request.method == "POST":
            serializer = ChatMessageCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            message = post_message(thread, request.user, serializer.validated_data)
            return Response(
                ChatMessageSerializer(message).data,
                status=status.HTTP_201_CREATED,
            )

        # GET — cursor-paginated history (newest first), per API-DESIGN.md
        queryset = thread.messages.select_related("sender").all()
        paginator = TimeOrderedCursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ChatMessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        thread = self.get_object()
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target = thread.messages.get(id=serializer.validated_data["message_id"])
        except ChatMessage.DoesNotExist:
            raise NotFound("Message not found in this thread.")
        count = mark_read(thread, request.user, target)
        return Response({"marked_read": count})
