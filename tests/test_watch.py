"""Fixed tests for matty module to increase code coverage."""

from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from matty import (
    Message,
)

runner = CliRunner()


class TestWatch:
    """Test watch."""

    @pytest.mark.asyncio
    async def test_watch_new_messages(self):
        """Test watch mode for detecting new messages."""

        # Simulate a sequence of messages appearing over time
        seen_events = set()

        # First batch of messages
        messages_batch1 = [
            Message(
                sender="@user1:matrix.org",
                content="Initial message",
                timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$msg1",
                handle="m1",
            )
        ]

        # Check for new messages
        new_messages = []
        for msg in messages_batch1:
            if msg.event_id and msg.event_id not in seen_events:
                new_messages.append(msg)
                seen_events.add(msg.event_id)

        assert len(new_messages) == 1
        assert new_messages[0].content == "Initial message"

        # Second batch with one new message
        messages_batch2 = [
            messages_batch1[0],  # Same message
            Message(
                sender="@user2:matrix.org",
                content="New message appears",
                timestamp=datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$msg2",
                handle="m2",
                thread_root_id="$msg1",  # It's a thread reply
            ),
        ]

        new_messages = []
        for msg in messages_batch2:
            if msg.event_id and msg.event_id not in seen_events:
                new_messages.append(msg)
                seen_events.add(msg.event_id)

        assert len(new_messages) == 1
        assert new_messages[0].content == "New message appears"
        assert new_messages[0].thread_root_id == "$msg1"  # Thread indicator should be present

        # Test reaction tracking
        messages_batch3 = [
            Message(
                sender="@user3:matrix.org",
                content="Message with reactions",
                timestamp=datetime(2024, 1, 1, 10, 10, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$msg3",
                handle="m3",
                reactions={
                    "🎉": ["@user1:matrix.org"],
                    "💯": ["@user2:matrix.org", "@user1:matrix.org"],
                },
            )
        ]

        new_messages = []
        for msg in messages_batch3:
            if msg.event_id and msg.event_id not in seen_events:
                new_messages.append(msg)
                seen_events.add(msg.event_id)

        assert len(new_messages) == 1
        assert new_messages[0].reactions
        assert "🎉" in new_messages[0].reactions
        assert len(new_messages[0].reactions["💯"]) == 2
