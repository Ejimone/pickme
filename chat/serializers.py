from rest_framework import serializers

from chat.models import ChatMessage, ChatThread


class ChatThreadSerializer(serializers.ModelSerializer):
    # All three come from annotations added in ChatThreadViewSet.get_queryset,
    # computed for the requesting user (see chat.services.annotate_thread_summary).
    unread_count = serializers.IntegerField(read_only=True)
    last_message_at = serializers.DateTimeField(read_only=True)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = ChatThread
        fields = [
            "id",
            "context_type",
            "carpool_group",
            "trip",
            "created_at",
            "unread_count",
            "last_message_at",
            "last_message",
        ]

    def get_last_message(self, obj):
        created = getattr(obj, "last_message_at", None)
        if created is None:
            return None  # no messages yet
        return {
            "content": getattr(obj, "last_message_content", None),
            "sender_name": getattr(obj, "last_message_sender_name", None),
            "message_type": getattr(obj, "last_message_type", None),
            "created_at": created,
        }


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.full_name", read_only=True)

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "thread",
            "sender",
            "sender_name",
            "content",
            "attachment_url",
            "message_type",
            "created_at",
        ]
        read_only_fields = ["thread", "sender"]


class ChatMessageCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["content", "attachment_url", "message_type"]

    def validate(self, attrs):
        if not attrs.get("content") and not attrs.get("attachment_url"):
            raise serializers.ValidationError(
                "A message needs content or an attachment."
            )
        return attrs


class MarkReadSerializer(serializers.Serializer):
    message_id = serializers.UUIDField()
