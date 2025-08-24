"""More tests to reach >90% coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import AsyncClient

from matty import (
    _get_thread_messages,
)


class TestThreadMessages:
    """Test thread message handling."""

    @pytest.mark.asyncio
    async def test_get_thread_messages_simple(self):
        """Test getting thread messages."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock thread messages
        msg1 = MagicMock(spec=RoomMessageText)
        msg1.sender = "@alice:matrix.org"
        msg1.body = "Thread root"
        msg1.server_timestamp = 1704110400000
        msg1.event_id = "$root123"
        msg1.source = {
            "content": {
                "body": "Thread root",
                "msgtype": "m.text",
                "m.relates_to": {"rel_type": "m.thread", "event_id": "$root123"},
            }
        }

        mock_response = MagicMock()
        mock_response.chunk = [msg1]

        client.room_messages = AsyncMock(return_value=mock_response)

        with patch("matty._get_or_create_handle", return_value="m1"):
            messages = await _get_thread_messages(client, "!room:matrix.org", "$root123")

        assert len(messages) > 0
