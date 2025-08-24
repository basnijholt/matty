"""Additional tests to improve coverage to >90%."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import AsyncClient
from typer.testing import CliRunner

from matty import (
    _get_message_by_handle,
    _get_thread_messages,
    _get_threads,
)

runner = CliRunner()


class TestThreadHandling:
    """Test thread handling functionality."""

    @pytest.mark.asyncio
    async def test_get_threads_empty(self):
        """Test getting threads from room with no threads."""
        client = MagicMock(spec=AsyncClient)

        mock_response = MagicMock()
        mock_response.chunk = []

        client.room_messages = AsyncMock(return_value=mock_response)

        threads = await _get_threads(client, "!room:matrix.org")
        assert threads == []

    @pytest.mark.asyncio
    async def test_get_thread_messages_with_deleted_root(self):
        """Test getting thread messages when root is deleted."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock events - only replies, no root
        reply1 = MagicMock(spec=RoomMessageText)
        reply1.sender = "@user:matrix.org"
        reply1.body = "Reply 1"
        reply1.server_timestamp = 1704110500000
        reply1.event_id = "$reply1"
        reply1.source = {
            "content": {
                "body": "Reply 1",
                "msgtype": "m.text",
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$missing_root",
                },
            }
        }

        mock_response = MagicMock()
        mock_response.chunk = [reply1]

        client.room_messages = AsyncMock(return_value=mock_response)

        with patch("matty._get_or_create_handle", return_value="m1"):
            messages = await _get_thread_messages(client, "!room:matrix.org", "$missing_root")

        # Should have placeholder + reply
        assert len(messages) == 2
        assert messages[0].sender == "[system]"
        assert "not available" in messages[0].content
        assert messages[1].content == "Reply 1"

    @pytest.mark.asyncio
    async def test_get_message_by_handle_not_found(self):
        """Test getting message by handle when not found."""
        client = MagicMock(spec=AsyncClient)

        mock_response = MagicMock()
        mock_response.chunk = []

        client.room_messages = AsyncMock(return_value=mock_response)

        with patch("matty._lookup_mapping", return_value=None):
            msg = await _get_message_by_handle(client, "!room:matrix.org", "m999")
            assert msg is None

    @pytest.mark.asyncio
    async def test_deleted_thread_root(self, mock_client):
        """Test handling of deleted thread root messages."""
        from datetime import timedelta
        from unittest.mock import patch

        from matty import Message, _get_thread_messages

        # Mock _get_messages to return thread replies without the root
        thread_root_id = "$deleted_root_event"

        # Create mock messages - only replies, no root message
        reply1 = Message(
            sender="@user1:matrix.org",
            content="First reply",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$reply1",
            thread_root_id=thread_root_id,
            reply_to_id=thread_root_id,
            is_thread_root=False,
        )

        reply2 = Message(
            sender="@user2:matrix.org",
            content="Second reply",
            timestamp=datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$reply2",
            thread_root_id=thread_root_id,
            reply_to_id="$reply1",
            is_thread_root=False,
        )

        # Mock _get_messages to return only the replies
        with patch("matty._get_messages") as mock_get_messages:
            mock_get_messages.return_value = [reply1, reply2]

            # Call _get_thread_messages
            thread_messages = await _get_thread_messages(
                mock_client, "!room:matrix.org", thread_root_id, limit=50
            )

            # Should have 3 messages: placeholder + 2 replies
            assert len(thread_messages) == 3

            # First message should be the placeholder
            placeholder = thread_messages[0]
            assert placeholder.sender == "[system]"
            assert (
                placeholder.content
                == "[Thread root message not available - may be deleted or outside message range]"
            )
            assert placeholder.event_id == thread_root_id
            assert placeholder.is_thread_root is True

            # Check timestamp is before first reply
            assert placeholder.timestamp < reply1.timestamp
            # Check timestamp is exactly 1 second before first reply
            expected_time = reply1.timestamp.replace(microsecond=0) - timedelta(seconds=1)
            assert placeholder.timestamp == expected_time

            # Other messages should be the replies in order
            assert thread_messages[1].event_id == "$reply1"
            assert thread_messages[2].event_id == "$reply2"

    @pytest.mark.asyncio
    async def test_normal_thread_with_root(self, mock_client):
        """Test normal thread with root message present."""
        from unittest.mock import patch

        from matty import Message, _get_thread_messages

        thread_root_id = "$root_event"

        # Create mock messages including root
        root = Message(
            sender="@user1:matrix.org",
            content="Thread root",
            timestamp=datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id=thread_root_id,
            is_thread_root=True,
        )

        reply = Message(
            sender="@user2:matrix.org",
            content="Reply",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$reply1",
            thread_root_id=thread_root_id,
            is_thread_root=False,
        )

        with patch("matty._get_messages") as mock_get_messages:
            mock_get_messages.return_value = [root, reply]

            thread_messages = await _get_thread_messages(
                mock_client, "!room:matrix.org", thread_root_id, limit=50
            )

            # Should have 2 messages: root + reply
            assert len(thread_messages) == 2
            assert thread_messages[0].event_id == thread_root_id
            assert thread_messages[0].sender == "@user1:matrix.org"
            assert thread_messages[1].event_id == "$reply1"
