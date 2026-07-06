import datetime

import pytest

from chat.models import ChatMessage, ChatReadReceipt, ChatThread
from trips.models import Trip

pytestmark = pytest.mark.django_db


class TestThreadAutoCreation:
    def test_group_gets_a_thread(self, group):
        thread = ChatThread.objects.get(carpool_group=group)
        assert thread.context_type == ChatThread.ContextType.CARPOOL_GROUP

    def test_trip_gets_a_thread(self, group, actors):
        users, _ = actors
        trip = Trip.objects.create(
            driver=users["a"], carpool_group=group, date=datetime.date(2026, 7, 6)
        )
        thread = ChatThread.objects.get(trip=trip)
        assert thread.context_type == ChatThread.ContextType.TRIP
        assert thread.carpool_group_id == group.id


class TestThreadScoping:
    def test_member_lists_thread(self, clients, thread):
        response = clients["a"].get("/api/v1/chat-threads/")
        assert response.status_code == 200
        ids = {row["id"] for row in response.data["results"]}
        assert str(thread.id) in ids

    def test_outsider_sees_no_threads(self, clients, thread):
        response = clients["d"].get("/api/v1/chat-threads/")
        assert response.data["results"] == []

    def test_outsider_cannot_retrieve_thread(self, clients, thread):
        assert (
            clients["d"].get(f"/api/v1/chat-threads/{thread.id}/").status_code == 404
        )

    def test_unauthenticated_rejected(self, thread):
        from rest_framework.test import APIClient

        assert APIClient().get("/api/v1/chat-threads/").status_code == 401


class TestMessages:
    def test_send_and_history(self, clients, thread):
        response = clients["a"].post(
            f"/api/v1/chat-threads/{thread.id}/messages/",
            {"content": "on my way"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["content"] == "on my way"

        # Member B reads history
        response = clients["b"].get(
            f"/api/v1/chat-threads/{thread.id}/messages/"
        )
        assert response.status_code == 200
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["content"] == "on my way"

    def test_history_is_cursor_paginated_newest_first(self, clients, thread, actors):
        users, _ = actors
        for i in range(3):
            ChatMessage.objects.create(
                thread=thread, sender=users["a"], content=f"msg {i}"
            )
        response = clients["a"].get(
            f"/api/v1/chat-threads/{thread.id}/messages/?page_size=2"
        )
        assert response.data["next"] is not None  # cursor link present
        contents = [m["content"] for m in response.data["results"]]
        assert contents == ["msg 2", "msg 1"]  # newest first

    def test_message_requires_content_or_attachment(self, clients, thread):
        response = clients["a"].post(
            f"/api/v1/chat-threads/{thread.id}/messages/", {}, format="json"
        )
        assert response.status_code == 400

    def test_outsider_cannot_send(self, clients, thread):
        response = clients["d"].post(
            f"/api/v1/chat-threads/{thread.id}/messages/",
            {"content": "hello"},
            format="json",
        )
        assert response.status_code in (403, 404)

    def test_outsider_cannot_read_history(self, clients, thread):
        assert (
            clients["d"]
            .get(f"/api/v1/chat-threads/{thread.id}/messages/")
            .status_code
            in (403, 404)
        )


class TestReadReceipts:
    def test_mark_read_up_to_message(self, clients, thread, actors):
        users, _ = actors
        messages = [
            ChatMessage.objects.create(
                thread=thread, sender=users["a"], content=f"m{i}"
            )
            for i in range(3)
        ]
        response = clients["b"].post(
            f"/api/v1/chat-threads/{thread.id}/read/",
            {"message_id": str(messages[1].id)},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["marked_read"] == 2  # m0 and m1
        assert ChatReadReceipt.objects.filter(user=users["b"]).count() == 2

    def test_mark_read_is_idempotent(self, clients, thread, actors):
        users, _ = actors
        msg = ChatMessage.objects.create(
            thread=thread, sender=users["a"], content="hi"
        )
        url = f"/api/v1/chat-threads/{thread.id}/read/"
        body = {"message_id": str(msg.id)}
        assert clients["b"].post(url, body, format="json").data["marked_read"] == 1
        assert clients["b"].post(url, body, format="json").data["marked_read"] == 0
        assert ChatReadReceipt.objects.filter(user=users["b"], message=msg).count() == 1

    def test_read_unknown_message_404(self, clients, thread):
        import uuid

        response = clients["a"].post(
            f"/api/v1/chat-threads/{thread.id}/read/",
            {"message_id": str(uuid.uuid4())},
            format="json",
        )
        assert response.status_code == 404
