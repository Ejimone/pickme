"""Chat-list summary fields on ChatThread: unread_count, last_message,
last_message_at, and most-recent-activity ordering."""

import pytest

from carpool.models import CarpoolGroup, CarpoolGroupMember
from chat.models import ChatMessage, ChatThread

pytestmark = pytest.mark.django_db


def _thread_row(resp_json, thread_id):
    for row in resp_json["results"]:
        if row["id"] == str(thread_id):
            return row
    return None


class TestSummaryFields:
    def test_last_message_and_unread_for_recipient(self, thread, actors, clients):
        users, _ = actors
        ChatMessage.objects.create(
            thread=thread, sender=users["a"], content="Heading to Kennedy"
        )
        resp = clients["b"].get("/api/v1/chat-threads/")
        row = _thread_row(resp.json(), thread.id)
        assert row["unread_count"] == 1
        assert row["last_message_at"] is not None
        assert row["last_message"]["content"] == "Heading to Kennedy"
        assert row["last_message"]["message_type"] == "text"
        assert row["last_message"]["sender_name"] == users["a"].full_name

    def test_empty_thread_has_null_last_message(self, thread, clients):
        resp = clients["a"].get("/api/v1/chat-threads/")
        row = _thread_row(resp.json(), thread.id)
        assert row["unread_count"] == 0
        assert row["last_message"] is None
        assert row["last_message_at"] is None

    def test_reading_clears_unread(self, thread, actors, clients):
        users, _ = actors
        msg = ChatMessage.objects.create(
            thread=thread, sender=users["a"], content="ping"
        )
        assert (
            _thread_row(clients["b"].get("/api/v1/chat-threads/").json(), thread.id)[
                "unread_count"
            ]
            == 1
        )
        clients["b"].post(
            f"/api/v1/chat-threads/{thread.id}/read/",
            {"message_id": str(msg.id)},
            format="json",
        )
        assert (
            _thread_row(clients["b"].get("/api/v1/chat-threads/").json(), thread.id)[
                "unread_count"
            ]
            == 0
        )

    def test_own_messages_not_counted_unread(self, thread, actors, clients):
        users, _ = actors
        ChatMessage.objects.create(thread=thread, sender=users["b"], content="mine")
        row = _thread_row(clients["b"].get("/api/v1/chat-threads/").json(), thread.id)
        assert row["unread_count"] == 0
        assert row["last_message"]["content"] == "mine"


class TestOrdering:
    def test_threads_ordered_by_recent_activity_nulls_last(
        self, thread, group, actors, clients, school
    ):
        users, families = actors
        # A second group → a second (empty) thread for family A.
        group2 = CarpoolGroup.objects.create(
            school=school, name="Afternoon Crew", created_by=users["a"]
        )
        CarpoolGroupMember.objects.create(
            carpool_group=group2, family=families["a"], role="admin"
        )
        thread2 = ChatThread.objects.get(carpool_group=group2)

        # Only the first thread has a message → it must sort first; empty last.
        ChatMessage.objects.create(thread=thread, sender=users["a"], content="hi")

        results = clients["a"].get("/api/v1/chat-threads/").json()["results"]
        ids = [r["id"] for r in results]
        assert ids.index(str(thread.id)) < ids.index(str(thread2.id))
        assert results[-1]["id"] == str(thread2.id)  # null activity sorts last


class TestImageMessage:
    def test_image_only_message_send(self, thread, clients):
        url = "https://res.cloudinary.com/demo/image/upload/chat/pic.jpg"
        resp = clients["a"].post(
            f"/api/v1/chat-threads/{thread.id}/messages/",
            {"attachment_url": url, "message_type": "image"},
            format="json",
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["attachment_url"] == url
        assert body["message_type"] == "image"
        assert body["content"] is None
