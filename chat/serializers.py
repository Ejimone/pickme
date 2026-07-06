from rest_framework import serializers

from chat.models import ChatMessage, ChatThread


class ChatThreadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatThread
        fields = [
            "id",
            "context_type",
            "carpool_group",
            "trip",
            "created_at",
        ]


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
