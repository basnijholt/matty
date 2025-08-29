"""Tests for streaming message functionality."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import ReactionEvent, RedactedEvent, RoomMessageText

from matty import OutputFormat, _stream_messages


class TestStreamingMessages:
    """Test streaming message functionality."""

    @pytest.mark.asyncio
    async def test_stream_loads_recent_messages(self):
        """Test that streaming loads recent messages on start."""
        # Mock client
        client = MagicMock()
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)
        client.add_event_callback = MagicMock()

        # Mock recent messages
        mock_messages = [
            MagicMock(
                sender="@alice:matrix.org",
                content="Hello world",
                timestamp=datetime.now(UTC),
                room_id="!test:matrix.org",
                event_id="$msg1",
                reactions={},
            ),
            MagicMock(
                sender="@bob:matrix.org",
                content="Hi there",
                timestamp=datetime.now(UTC),
                room_id="!test:matrix.org",
                event_id="$msg2",
                reactions={"👍": ["@alice:matrix.org"]},
            ),
        ]

        # Patch _get_messages to return mock messages
        with patch("matty._get_messages", AsyncMock(return_value=mock_messages)):
            # Run streaming with immediate timeout
            await _stream_messages(
                client, "!test:matrix.org", "Test Room", OutputFormat.rich, timeout=0.1
            )

        # Verify callbacks were registered
        assert (
            client.add_event_callback.call_count == 3
        )  # RoomMessageText, ReactionEvent, RedactedEvent

    @pytest.mark.asyncio
    async def test_stream_handles_new_messages(self):
        """Test that streaming handles new messages correctly."""
        client = MagicMock()
        room_id = "!test:matrix.org"

        # Store the callback when registered
        message_callback = None

        def capture_callback(callback, event_type):
            nonlocal message_callback
            if event_type == RoomMessageText:
                message_callback = callback

        client.add_event_callback = MagicMock(side_effect=capture_callback)
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)

        # Mock room and event
        mock_room = MagicMock()
        mock_room.room_id = room_id

        mock_event = MagicMock(spec=RoomMessageText)
        mock_event.sender = "@alice:matrix.org"
        mock_event.body = "New message"
        mock_event.event_id = "$new1"
        mock_event.server_timestamp = 1000000
        mock_event.source = {"content": {}}

        with patch("matty._get_messages", AsyncMock(return_value=[])):
            # Start streaming
            await _stream_messages(client, room_id, "Test Room", OutputFormat.rich, timeout=0.1)

            # Simulate new message arriving
            if message_callback:
                message_callback(mock_room, mock_event)

    @pytest.mark.asyncio
    async def test_stream_handles_edits(self):
        """Test that streaming handles message edits."""
        client = MagicMock()
        room_id = "!test:matrix.org"

        # Capture callback
        message_callback = None

        def capture_callback(callback, event_type):
            nonlocal message_callback
            if event_type == RoomMessageText:
                message_callback = callback

        client.add_event_callback = MagicMock(side_effect=capture_callback)
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)

        # Initial message
        initial_msg = MagicMock(
            sender="@alice:matrix.org",
            content="Original",
            timestamp=datetime.now(UTC),
            room_id=room_id,
            event_id="$orig1",
            reactions={},
        )

        with patch("matty._get_messages", AsyncMock(return_value=[initial_msg])):
            await _stream_messages(client, room_id, "Test Room", OutputFormat.rich, timeout=0.1)

            # Create edit event
            mock_room = MagicMock()
            mock_room.room_id = room_id

            edit_event = MagicMock(spec=RoomMessageText)
            edit_event.sender = "@alice:matrix.org"
            edit_event.body = "Edited message"
            edit_event.event_id = "$edit1"
            edit_event.server_timestamp = 2000000
            edit_event.source = {
                "content": {"m.relates_to": {"rel_type": "m.replace", "event_id": "$orig1"}}
            }

            # Simulate edit arriving
            if message_callback:
                message_callback(mock_room, edit_event)

    @pytest.mark.asyncio
    async def test_stream_handles_reactions(self):
        """Test that streaming handles reactions."""
        client = MagicMock()
        room_id = "!test:matrix.org"

        # Capture callbacks
        reaction_callback = None

        def capture_callback(callback, event_type):
            nonlocal reaction_callback
            if event_type == ReactionEvent:
                reaction_callback = callback

        client.add_event_callback = MagicMock(side_effect=capture_callback)
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)

        # Initial message
        initial_msg = MagicMock(
            sender="@alice:matrix.org",
            content="Test message",
            timestamp=datetime.now(UTC),
            room_id=room_id,
            event_id="$msg1",
            reactions={},
        )

        with patch("matty._get_messages", AsyncMock(return_value=[initial_msg])):
            await _stream_messages(client, room_id, "Test Room", OutputFormat.rich, timeout=0.1)

            # Create reaction event
            mock_room = MagicMock()
            mock_room.room_id = room_id

            reaction = MagicMock(spec=ReactionEvent)
            reaction.reacts_to = "$msg1"
            reaction.key = "👍"
            reaction.sender = "@bob:matrix.org"

            # Simulate reaction arriving
            if reaction_callback:
                reaction_callback(mock_room, reaction)

    @pytest.mark.asyncio
    async def test_stream_handles_deletions(self):
        """Test that streaming handles message deletions."""
        client = MagicMock()
        room_id = "!test:matrix.org"

        # Capture callbacks
        redaction_callback = None

        def capture_callback(callback, event_type):
            nonlocal redaction_callback
            if event_type == RedactedEvent:
                redaction_callback = callback

        client.add_event_callback = MagicMock(side_effect=capture_callback)
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)

        # Initial message
        initial_msg = MagicMock(
            sender="@alice:matrix.org",
            content="To be deleted",
            timestamp=datetime.now(UTC),
            room_id=room_id,
            event_id="$del1",
            reactions={},
        )

        with patch("matty._get_messages", AsyncMock(return_value=[initial_msg])):
            await _stream_messages(client, room_id, "Test Room", OutputFormat.rich, timeout=0.1)

            # Create redaction event
            mock_room = MagicMock()
            mock_room.room_id = room_id

            redaction = MagicMock(spec=RedactedEvent)
            redaction.redacts = "$del1"
            redaction.sender = "@alice:matrix.org"

            # Simulate deletion arriving
            if redaction_callback:
                redaction_callback(mock_room, redaction)

    @pytest.mark.asyncio
    async def test_stream_skips_duplicates(self):
        """Test that streaming skips duplicate messages."""
        client = MagicMock()
        room_id = "!test:matrix.org"

        message_callback = None

        def capture_callback(callback, event_type):
            nonlocal message_callback
            if event_type == RoomMessageText:
                message_callback = callback

        client.add_event_callback = MagicMock(side_effect=capture_callback)
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)

        # Initial message that will also come through sync
        initial_msg = MagicMock(
            sender="@alice:matrix.org",
            content="Existing message",
            timestamp=datetime.now(UTC),
            room_id=room_id,
            event_id="$dup1",
            reactions={},
        )

        with patch("matty._get_messages", AsyncMock(return_value=[initial_msg])):
            await _stream_messages(client, room_id, "Test Room", OutputFormat.rich, timeout=0.1)

            # Simulate same message coming through sync
            mock_room = MagicMock()
            mock_room.room_id = room_id

            duplicate_event = MagicMock(spec=RoomMessageText)
            duplicate_event.sender = "@alice:matrix.org"
            duplicate_event.body = "Existing message"
            duplicate_event.event_id = "$dup1"  # Same ID
            duplicate_event.server_timestamp = 1000000
            duplicate_event.source = {"content": {}}

            # This should be skipped
            if message_callback:
                message_callback(mock_room, duplicate_event)

    @pytest.mark.asyncio
    async def test_stream_with_timeout(self):
        """Test streaming with timeout."""
        client = MagicMock()

        # Mock sync_forever to simulate timeout
        async def mock_sync(*args, **kwargs):  # noqa: ARG001
            await asyncio.sleep(0.2)

        client.sync_forever = AsyncMock(side_effect=mock_sync)
        client.add_event_callback = MagicMock()

        with patch("matty._get_messages", AsyncMock(return_value=[])):
            # This should timeout after 0.1 seconds
            await _stream_messages(
                client, "!test:matrix.org", "Test Room", OutputFormat.rich, timeout=0.1
            )

    @pytest.mark.asyncio
    async def test_stream_simple_format(self):
        """Test streaming with simple output format."""
        client = MagicMock()
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)
        client.add_event_callback = MagicMock()

        # Simple format doesn't use Live display or load recent messages
        await _stream_messages(
            client, "!test:matrix.org", "Test Room", OutputFormat.simple, timeout=0.1
        )

        # Should still register callback for simple format
        assert client.add_event_callback.called

    @pytest.mark.asyncio
    async def test_stream_json_format(self):
        """Test streaming with JSON output format."""
        client = MagicMock()
        client.sync_forever = AsyncMock(side_effect=asyncio.TimeoutError)
        client.add_event_callback = MagicMock()

        await _stream_messages(
            client, "!test:matrix.org", "Test Room", OutputFormat.json, timeout=0.1
        )

        # Should register callback for JSON format
        assert client.add_event_callback.called
