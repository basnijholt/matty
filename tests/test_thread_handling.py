"""Additional tests to improve coverage to >90%."""

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
