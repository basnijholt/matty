"""Additional tests to improve coverage to >90%."""

from unittest.mock import MagicMock

from nio import AsyncClient, MatrixRoom
from typer.testing import CliRunner

from matty import (
    _build_edit_content,
    _build_message_content,
    _extract_thread_and_reply,
    _get_event_content,
    _get_relation,
    _get_room_users,
    _is_relation_type,
)

runner = CliRunner()


class TestMatrixProtocolHelpers:
    """Test Matrix protocol helper functions."""

    def test_get_event_content_with_content(self):
        """Test getting event content when present."""
        event = MagicMock()
        event.source = {"content": {"body": "test", "msgtype": "m.text"}}
        content = _get_event_content(event)
        assert content == {"body": "test", "msgtype": "m.text"}

    def test_get_event_content_without_content(self):
        """Test getting event content when missing."""
        event = MagicMock()
        event.source = {}
        content = _get_event_content(event)
        assert content == {}

    def test_get_relation_with_relation(self):
        """Test getting relation when present."""
        content = {"m.relates_to": {"rel_type": "m.thread", "event_id": "$123"}}
        relation = _get_relation(content)
        assert relation == {"rel_type": "m.thread", "event_id": "$123"}

    def test_get_relation_without_relation(self):
        """Test getting relation when missing."""
        content = {"body": "test"}
        relation = _get_relation(content)
        assert relation is None

    def test_is_relation_type_matching(self):
        """Test checking relation type when matching."""
        content = {"m.relates_to": {"rel_type": "m.thread", "event_id": "$123"}}
        assert _is_relation_type(content, "m.thread") is True
        assert _is_relation_type(content, "m.replace") is False

    def test_is_relation_type_no_relation(self):
        """Test checking relation type with no relation."""
        content = {"body": "test"}
        assert _is_relation_type(content, "m.thread") is False

    def test_extract_thread_and_reply_thread(self):
        """Test extracting thread relation."""
        content = {"m.relates_to": {"rel_type": "m.thread", "event_id": "$thread123"}}
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id == "$thread123"
        assert reply_id is None

    def test_extract_thread_and_reply_reply(self):
        """Test extracting reply relation."""
        content = {"m.relates_to": {"m.in_reply_to": {"event_id": "$reply123"}}}
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id is None
        assert reply_id == "$reply123"

    def test_extract_thread_and_reply_both(self):
        """Test extracting both thread and reply relations."""
        content = {
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": "$thread456",
                "m.in_reply_to": {"event_id": "$reply456"},
            }
        }
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id == "$thread456"
        assert reply_id == "$reply456"

    def test_extract_thread_and_reply_none(self):
        """Test extracting when no relations."""
        content = {"body": "test"}
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id is None
        assert reply_id is None

    def test_build_message_content_simple(self):
        """Test building simple message content."""
        content = _build_message_content("Hello world")
        assert content == {"msgtype": "m.text", "body": "Hello world"}

    def test_build_message_content_with_formatted(self):
        """Test building message with formatted body."""
        content = _build_message_content("Hello", formatted_body="<b>Hello</b>")
        assert content["body"] == "Hello"
        assert content["formatted_body"] == "<b>Hello</b>"
        assert content["format"] == "org.matrix.custom.html"

    def test_build_message_content_with_mentions(self):
        """Test building message with mentions."""
        content = _build_message_content("Hello @user", mentioned_user_ids=["@user:matrix.org"])
        assert content["m.mentions"] == {"user_ids": ["@user:matrix.org"]}

    def test_build_message_content_thread(self):
        """Test building thread message."""
        content = _build_message_content("Thread reply", thread_root_id="$thread789")
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$thread789"

    def test_build_message_content_reply(self):
        """Test building reply message."""
        content = _build_message_content("Reply", reply_to_id="$msg789")
        assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$msg789"

    def test_build_message_content_thread_reply(self):
        """Test building thread reply with reply-to."""
        content = _build_message_content(
            "Thread reply", thread_root_id="$thread999", reply_to_id="$msg999"
        )
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$thread999"
        assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$msg999"

    def test_build_edit_content_simple(self):
        """Test building simple edit content."""
        content = _build_edit_content("$original123", "Edited text")
        assert content["body"] == "* Edited text"
        assert content["m.new_content"]["body"] == "Edited text"
        assert content["m.relates_to"]["rel_type"] == "m.replace"
        assert content["m.relates_to"]["event_id"] == "$original123"

    def test_build_edit_content_with_formatted(self):
        """Test building edit with formatted body."""
        content = _build_edit_content("$original456", "Edited", formatted_body="<b>Edited</b>")
        assert content["formatted_body"] == "* <b>Edited</b>"
        assert content["m.new_content"]["formatted_body"] == "<b>Edited</b>"
        assert "format" in content
        assert "format" in content["m.new_content"]

    def test_build_edit_content_with_mentions(self):
        """Test building edit with mentions."""
        content = _build_edit_content(
            "$original789", "Edited @user", mentioned_user_ids=["@user:matrix.org"]
        )
        assert content["m.mentions"] == {"user_ids": ["@user:matrix.org"]}
        assert content["m.new_content"]["m.mentions"] == {"user_ids": ["@user:matrix.org"]}

    def test_get_room_users(self):
        """Test getting users from a room."""
        client = MagicMock(spec=AsyncClient)
        room = MagicMock(spec=MatrixRoom)
        room.users = {
            "@user1:matrix.org": None,
            "@user2:matrix.org": None,
            "@user3:matrix.org": None,
        }
        client.rooms = {"!room:matrix.org": room}

        users = _get_room_users(client, "!room:matrix.org")
        assert len(users) == 3
        assert "@user1:matrix.org" in users
        assert "@user2:matrix.org" in users
        assert "@user3:matrix.org" in users

    def test_get_room_users_not_found(self):
        """Test getting users from non-existent room."""
        client = MagicMock(spec=AsyncClient)
        client.rooms = {}
        users = _get_room_users(client, "!nonexistent:matrix.org")
        assert users == []
