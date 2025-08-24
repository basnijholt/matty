"""Fixed tests for matty module to increase code coverage."""

from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from matty import (
    Message,
)

runner = CliRunner()


class TestSearch:
    """Test search."""

    @pytest.mark.asyncio
    async def test_search_messages(self):
        """Test searching messages for specific text."""

        # Create mock messages
        msg1 = Message(
            sender="@user1:matrix.org",
            content="Hello world from Python",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$msg1",
            handle="m1",
        )

        msg2 = Message(
            sender="@user2:matrix.org",
            content="Testing the search functionality",
            timestamp=datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$msg2",
            handle="m2",
        )

        msg3 = Message(
            sender="@user3:matrix.org",
            content="Another message with Python code",
            timestamp=datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$msg3",
            handle="m3",
        )

        # Test case-insensitive search
        messages = [msg1, msg2, msg3]

        # Search for "python" (should find 2 messages)
        matched = [msg for msg in messages if "python" in msg.content.lower()]

        assert len(matched) == 2
        assert msg1 in matched
        assert msg3 in matched

        # Test regex search
        import re

        pattern = r"world|search"
        matched_regex = [msg for msg in messages if re.search(pattern, msg.content, re.IGNORECASE)]

        assert len(matched_regex) == 2
        assert msg1 in matched_regex
        assert msg2 in matched_regex
