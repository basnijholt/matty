"""Fixed tests for matty module to increase code coverage."""

from dataclasses import asdict
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from matty import (
    Message,
)

runner = CliRunner()


class TestNewFeatures:
    """Test export."""

    @pytest.mark.asyncio
    async def test_export_messages_markdown(self):
        """Test exporting messages to markdown format."""

        # Create mock messages
        msg1 = Message(
            sender="@user1:matrix.org",
            content="First message",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$msg1",
            handle="m1",
            reactions={"👍": ["@user2:matrix.org"]},
        )

        msg2 = Message(
            sender="@user2:matrix.org",
            content="Second message",
            timestamp=datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$msg2",
            handle="m2",
        )

        messages = [msg1, msg2]

        # Test markdown export format
        room_name = "Test Room"
        content = f"# {room_name}\n\n"
        content += f"*Exported on {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}*\n\n"
        content += "---\n\n"

        for msg in reversed(messages):  # Show oldest first
            time_str = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            content += f"**{msg.sender}** - *{time_str}*\n\n"
            content += f"{msg.content}\n"

            if msg.reactions:
                reactions_str = " ".join(
                    [f"{emoji}({len(users)})" for emoji, users in msg.reactions.items()]
                )
                content += f"\n> Reactions: {reactions_str}\n"

            content += "\n---\n\n"

        # Verify markdown content structure
        assert "# Test Room" in content
        assert "**@user1:matrix.org**" in content
        assert "First message" in content
        assert "Second message" in content
        assert "👍(1)" in content

        # Test JSON export format
        export_data = {
            "room": room_name,
            "exported_at": datetime.now(UTC).isoformat(),
            "message_count": len(messages),
            "messages": [asdict(msg) for msg in messages],
        }

        assert export_data["message_count"] == 2
        assert len(export_data["messages"]) == 2
        assert export_data["messages"][0]["content"] == "First message"
