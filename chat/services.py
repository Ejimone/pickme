"""Chat visibility, the shared message-post path, and read-receipt marking.

post_message / mark_read are shared by the WebSocket consumer and the REST
fallback endpoints so both paths broadcast identically.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Q


def threads_visible_to(user):
    """Q filter for threads the user may read/post in: carpool-group threads
    where the user's family is a member, or trip threads the user is party to
    (driver, family with a child at a stop, or a group member)."""
    return (
        Q(carpool_group__members__family__members__user=user)
        | Q(trip__driver=user)
        | Q(trip__stops__children__child__family__members__user=user)
        | Q(trip__carpool_group__members__family__members__user=user)
    )


def user_can_access_thread(user, thread_id):
    from chat.models import ChatThread

    return ChatThread.objects.filter(
        threads_visible_to(user), id=thread_id
    ).exists()


def annotate_thread_summary(queryset, user):
    """Add per-user chat-list summary fields via correlated subqueries (no N+1
    over messages) and order by most-recent activity, nulls last:

      - unread_count: messages not sent by the user and not yet read by them
        (read state = a ChatReadReceipt per (message, user))
      - last_message_at / last_message_{content,type,sender_name}: the most
        recent message's fields (all null when the thread has no messages)
    """
    from django.db.models import Count, F, IntegerField, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    from chat.models import ChatMessage

    latest = ChatMessage.objects.filter(thread=OuterRef("pk")).order_by(
        "-created_at"
    )
    unread = (
        ChatMessage.objects.filter(thread=OuterRef("pk"))
        .exclude(sender=user)  # your own messages aren't "unread"
        .exclude(read_receipts__user=user)  # already receipted = read
        .order_by()
        .values("thread")
        .annotate(c=Count("id"))
        .values("c")
    )
    return queryset.annotate(
        last_message_at=Subquery(latest.values("created_at")[:1]),
        last_message_content=Subquery(latest.values("content")[:1]),
        last_message_type=Subquery(latest.values("message_type")[:1]),
        last_message_sender_name=Subquery(
            latest.values("sender__full_name")[:1]
        ),
        unread_count=Coalesce(
            Subquery(unread, output_field=IntegerField()), Value(0)
        ),
    ).order_by(F("last_message_at").desc(nulls_last=True))


def broadcast_to_thread(thread_id, payload):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(f"chat_{thread_id}", payload)


def serialize_message(message):
    return {
        "id": str(message.id),
        "thread": str(message.thread_id),
        "sender": str(message.sender_id),
        "sender_name": message.sender.full_name,
        "content": message.content,
        "attachment_url": message.attachment_url,
        "message_type": message.message_type,
        "created_at": message.created_at.isoformat(),
    }


def post_message(thread, sender, data):
    """Create a ChatMessage and broadcast `message.new` to the thread group.
    `data` carries content and/or attachment_url plus optional message_type."""
    from chat.models import ChatMessage

    message = ChatMessage.objects.create(
        thread=thread,
        sender=sender,
        content=data.get("content"),
        attachment_url=data.get("attachment_url"),
        message_type=data.get("message_type", ChatMessage.MessageType.TEXT),
    )
    broadcast_to_thread(
        thread.id,
        {"type": "message.new", "message": serialize_message(message)},
    )
    return message


def mark_read(thread, user, up_to_message):
    """Record read receipts for every message in the thread up to and
    including `up_to_message` that the user hasn't already receipted, then
    broadcast `message.read`. Idempotent."""
    from chat.models import ChatMessage, ChatReadReceipt

    unseen = ChatMessage.objects.filter(
        thread=thread, created_at__lte=up_to_message.created_at
    ).exclude(read_receipts__user=user)
    receipts = [
        ChatReadReceipt(message=message, user=user)
        for message in unseen.only("id")
    ]
    ChatReadReceipt.objects.bulk_create(receipts, ignore_conflicts=True)
    broadcast_to_thread(
        thread.id,
        {
            "type": "message.read",
            "thread": str(thread.id),
            "user": str(user.id),
            "up_to_message": str(up_to_message.id),
            "count": len(receipts),
        },
    )
    return len(receipts)
