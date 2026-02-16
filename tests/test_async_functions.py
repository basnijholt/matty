"""Fixed tests for matty module to increase code coverage."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from nio import (
    AsyncClient,
    LoginResponse,
    MatrixRoom,
    RoomSendResponse,
)
from typer.testing import CliRunner

from matty import (
    Config,
    _create_client,
    _find_room,
    _get_message_by_handle,
    _get_messages,
    _get_rooms,
    _get_thread_messages,
    _get_threads,
    _login,
    _send_message,
    _sync_client,
)

runner = CliRunner()


class TestAsyncFunctions:
    """Test async utility functions."""

    @pytest.mark.asyncio
    async def test_create_client(self):
        """Test client creation."""
        config = Config(
            homeserver="https://matrix.org",
            username="test",
            password="pass",
            ssl_verify=True,
        )
        client = await _create_client(config)
        assert isinstance(client, AsyncClient)
        assert client.homeserver == "https://matrix.org"

    @pytest.mark.asyncio
    async def test_login_success(self):
        """Test successful login."""
        client = MagicMock(spec=AsyncClient)
        client.login = AsyncMock(
            return_value=LoginResponse("@user:matrix.org", "device123", "token123")
        )

        result = await _login(client, "password")
        assert result is True

    @pytest.mark.asyncio
    async def test_sync_client(self):
        """Test client sync."""
        client = MagicMock(spec=AsyncClient)
        sync_response = MagicMock()
        client.sync = AsyncMock(return_value=sync_response)

        await _sync_client(client, timeout=1000)
        client.sync.assert_called_once_with(timeout=1000)

    @pytest.mark.asyncio
    async def test_get_rooms(self):
        """Test getting rooms."""
        client = MagicMock(spec=AsyncClient)

        # Create mock rooms - users should be a dict, not a list
        room1 = MagicMock(spec=MatrixRoom)
        room1.room_id = "!room1:matrix.org"
        room1.display_name = "Room 1"
        room1.member_count = 5
        room1.users = {
            "@user1:matrix.org": None,
            "@user2:matrix.org": None,
            "@user3:matrix.org": None,
            "@user4:matrix.org": None,
            "@user5:matrix.org": None,
        }
        room1.topic = "Topic 1"

        room2 = MagicMock(spec=MatrixRoom)
        room2.room_id = "!room2:matrix.org"
        room2.display_name = "Room 2"
        room2.member_count = 10
        room2.users = {f"@user{i}:matrix.org": None for i in range(10)}
        room2.topic = None

        client.rooms = {"!room1:matrix.org": room1, "!room2:matrix.org": room2}

        rooms = await _get_rooms(client)
        assert len(rooms) == 2
        assert rooms[0].name == "Room 1"
        assert rooms[1].member_count == 10

    @pytest.mark.asyncio
    async def test_find_room(self):
        """Test finding a room."""
        client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room1:matrix.org"
        room.display_name = "Test Room"
        room.users = {"@user1:matrix.org": None}
        room.topic = None

        client.rooms = {"!room1:matrix.org": room}

        # Test finding by name
        result = await _find_room(client, "Test Room")
        assert result == ("!room1:matrix.org", "Test Room")

        # Test finding by ID
        result = await _find_room(client, "!room1:matrix.org")
        assert result == ("!room1:matrix.org", "Test Room")

        # Test not found
        result = await _find_room(client, "Nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_room_by_number(self):
        """Test finding a room by numeric index (matching `matty rooms` output)."""
        client = MagicMock(spec=AsyncClient)

        room1 = MagicMock(spec=MatrixRoom)
        room1.room_id = "!room1:matrix.org"
        room1.display_name = "Alpha"
        room1.users = {"@user1:matrix.org": None}
        room1.topic = None

        room2 = MagicMock(spec=MatrixRoom)
        room2.room_id = "!room2:matrix.org"
        room2.display_name = "Beta"
        room2.users = {"@user1:matrix.org": None}
        room2.topic = None

        client.rooms = {
            "!room1:matrix.org": room1,
            "!room2:matrix.org": room2,
        }

        # Test finding by number (1-based index)
        result = await _find_room(client, "1")
        assert result == ("!room1:matrix.org", "Alpha")

        result = await _find_room(client, "2")
        assert result == ("!room2:matrix.org", "Beta")

        # Test out of range
        result = await _find_room(client, "0")
        assert result is None

        result = await _find_room(client, "3")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_room_by_alias(self):
        """Test finding a room by alias."""
        client = MagicMock(spec=AsyncClient)

        # Mock room_resolve_alias response
        mock_alias_response = MagicMock()
        mock_alias_response.room_id = "!room1:matrix.org"
        client.room_resolve_alias = AsyncMock(return_value=mock_alias_response)

        # Mock the room
        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room1:matrix.org"
        room.display_name = "Admin Room"
        room.users = {"@admin:matrix.org": None}
        room.topic = None

        client.rooms = {"!room1:matrix.org": room}

        # Test finding by alias
        result = await _find_room(client, "#admins:matrix.org")
        assert result == ("!room1:matrix.org", "Admin Room")
        client.room_resolve_alias.assert_called_once_with("#admins:matrix.org")

    @pytest.mark.asyncio
    async def test_find_room_by_alias_not_joined(self):
        """Test finding a room by alias when not in the room."""
        client = MagicMock(spec=AsyncClient)

        # Mock room_resolve_alias response
        mock_alias_response = MagicMock()
        mock_alias_response.room_id = "!room2:matrix.org"
        client.room_resolve_alias = AsyncMock(return_value=mock_alias_response)

        # Room is not in our joined rooms
        client.rooms = {}

        # Test finding by alias - should return the resolved ID and the alias as name
        result = await _find_room(client, "#other:matrix.org")
        assert result == ("!room2:matrix.org", "#other:matrix.org")
        client.room_resolve_alias.assert_called_once_with("#other:matrix.org")

    @pytest.mark.asyncio
    async def test_find_room_by_alias_error(self):
        """Test finding a room by alias when resolution fails."""
        from nio import ErrorResponse

        client = MagicMock(spec=AsyncClient)

        # Mock room_resolve_alias to return an error
        client.room_resolve_alias = AsyncMock(return_value=ErrorResponse("Not found"))

        # Mock a room with a similar name to fall back to
        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room1:matrix.org"
        room.display_name = "#admins:matrix.org"  # Display name matches the alias
        room.users = {"@admin:matrix.org": None}
        room.topic = None

        client.rooms = {"!room1:matrix.org": room}

        # Test finding by alias - should fall back to name search
        result = await _find_room(client, "#admins:matrix.org")
        assert result == ("!room1:matrix.org", "#admins:matrix.org")
        client.room_resolve_alias.assert_called_once_with("#admins:matrix.org")

    @pytest.mark.asyncio
    async def test_get_messages(self):
        """Test getting messages from a room."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock RoomMessageText event
        mock_event = MagicMock(spec=RoomMessageText)
        mock_event.sender = "@user:matrix.org"
        mock_event.body = "Test message"
        mock_event.server_timestamp = 1704110400000
        mock_event.event_id = "$event123"
        mock_event.source = {"content": {"body": "Test message", "msgtype": "m.text"}}

        # Create mock response
        mock_response = MagicMock()
        mock_response.chunk = [mock_event]

        client.room_messages = AsyncMock(return_value=mock_response)

        messages = await _get_messages(client, "!room:matrix.org", limit=10)
        assert len(messages) == 1
        assert messages[0].content == "Test message"
        assert messages[0].sender == "@user:matrix.org"

    @pytest.mark.asyncio
    async def test_get_messages_with_edit(self):
        """Test getting messages with edits."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create original message
        original_msg = MagicMock(spec=RoomMessageText)
        original_msg.sender = "@user:matrix.org"
        original_msg.body = "Original message"
        original_msg.server_timestamp = 1704110400000
        original_msg.event_id = "$event123"
        original_msg.source = {"content": {"body": "Original message", "msgtype": "m.text"}}

        # Create edit event
        edit_msg = MagicMock(spec=RoomMessageText)
        edit_msg.sender = "@user:matrix.org"
        edit_msg.body = "* Edited message"
        edit_msg.server_timestamp = 1704110500000
        edit_msg.event_id = "$edit456"
        edit_msg.source = {
            "content": {
                "body": "* Edited message",
                "msgtype": "m.text",
                "m.new_content": {
                    "body": "Edited message",
                    "msgtype": "m.text",
                },
                "m.relates_to": {
                    "rel_type": "m.replace",
                    "event_id": "$event123",
                },
            }
        }

        # Create mock response with both messages
        mock_response = MagicMock()
        mock_response.chunk = [original_msg, edit_msg]

        client.room_messages = AsyncMock(return_value=mock_response)

        messages = await _get_messages(client, "!room:matrix.org", limit=10)
        assert len(messages) == 1  # Only the original message should appear
        assert "Edited message" in messages[0].content
        assert "[edited]" in messages[0].content
        assert messages[0].sender == "@user:matrix.org"

    @pytest.mark.asyncio
    async def test_send_message_reply(self):
        """Test sending a reply message."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse("$new_event123", "!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)
        # Add rooms attribute for mention parsing
        client.rooms = {
            "!room:matrix.org": MagicMock(users={"@user1:matrix.org": {}, "@user2:matrix.org": {}})
        }

        result = await _send_message(
            client,
            "!room:matrix.org",
            "Reply message",
            reply_to_id="$original123",
        )
        assert result is True

        # Check reply structure
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert "m.relates_to" in content
        assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$original123"

    @pytest.mark.asyncio
    async def test_send_message_with_mentions(self):
        """Test sending a message with mentions."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse("$new_event456", "!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)
        # Add rooms attribute with users for mention parsing
        room_mock = MagicMock()
        room_mock.users = {"@alice:matrix.org": {}, "@bob:matrix.org": {}}
        client.rooms = {"!room:matrix.org": room_mock}

        result = await _send_message(
            client,
            "!room:matrix.org",
            "@alice please check this",
        )
        assert result is True

        # Check that formatted_body was added with mention
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert content["body"] == "@alice please check this"
        assert "formatted_body" in content
        assert "@alice:matrix.org" in content["formatted_body"]
        assert '<a href="https://matrix.to/#/@alice:matrix.org">' in content["formatted_body"]
        # Check that m.mentions field is properly set
        assert "m.mentions" in content
        assert content["m.mentions"]["user_ids"] == ["@alice:matrix.org"]

    @pytest.mark.asyncio
    async def test_send_message_with_multiple_mentions(self):
        """Test sending a message with multiple mentions."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse("$new_event789", "!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)
        # Add rooms attribute with users for mention parsing
        room_mock = MagicMock()
        room_mock.users = {
            "@alice:matrix.org": {},
            "@bob:matrix.org": {},
            "@charlie:matrix.org": {},
        }
        client.rooms = {"!room:matrix.org": room_mock}

        result = await _send_message(
            client,
            "!room:matrix.org",
            "@alice @bob please review this",
        )
        assert result is True

        # Check that m.mentions field contains both users
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert "m.mentions" in content
        assert set(content["m.mentions"]["user_ids"]) == {
            "@alice:matrix.org",
            "@bob:matrix.org",
        }
        assert len(content["m.mentions"]["user_ids"]) == 2

    @pytest.mark.asyncio
    async def test_send_message_without_mentions(self):
        """Test sending a message without mentions."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse("$new_event999", "!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)
        # Add rooms attribute for mention parsing
        room_mock = MagicMock()
        room_mock.users = {"@alice:matrix.org": {}, "@bob:matrix.org": {}}
        client.rooms = {"!room:matrix.org": room_mock}

        result = await _send_message(
            client,
            "!room:matrix.org",
            "No mentions in this message",
        )
        assert result is True

        # Check that m.mentions field is NOT present when no mentions
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert "m.mentions" not in content
        assert content["body"] == "No mentions in this message"
        assert "formatted_body" not in content  # No HTML formatting needed

    @pytest.mark.asyncio
    async def test_send_message_error(self):
        """Test message sending error."""
        client = MagicMock(spec=AsyncClient)
        # The function catches exceptions and returns False
        client.room_send = AsyncMock(side_effect=Exception("Send failed"))

        result = await _send_message(client, "!room:matrix.org", "Test")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_threads(self):
        """Test getting threads from a room."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock events - one thread root, one regular
        thread_event = MagicMock(spec=RoomMessageText)
        thread_event.sender = "@user:matrix.org"
        thread_event.body = "Thread root"
        thread_event.server_timestamp = 1704110400000
        thread_event.event_id = "$thread1"
        thread_event.source = {"content": {"body": "Thread root", "msgtype": "m.text"}}

        # Create a reply to make it a thread root
        reply_event = MagicMock(spec=RoomMessageText)
        reply_event.sender = "@user:matrix.org"
        reply_event.body = "Thread reply"
        reply_event.server_timestamp = 1704110500000
        reply_event.event_id = "$reply1"
        reply_event.source = {
            "content": {
                "body": "Thread reply",
                "msgtype": "m.text",
                "m.relates_to": {"rel_type": "m.thread", "event_id": "$thread1"},
            }
        }

        regular_event = MagicMock(spec=RoomMessageText)
        regular_event.sender = "@user:matrix.org"
        regular_event.body = "Regular message"
        regular_event.server_timestamp = 1704110600000
        regular_event.event_id = "$event2"
        regular_event.source = {"content": {"body": "Regular message", "msgtype": "m.text"}}

        mock_response = MagicMock()
        mock_response.chunk = [thread_event, reply_event, regular_event]

        client.room_messages = AsyncMock(return_value=mock_response)

        threads = await _get_threads(client, "!room:matrix.org")
        assert len(threads) == 1
        assert threads[0].event_id == "$thread1"

    @pytest.mark.asyncio
    async def test_get_thread_messages(self):
        """Test getting messages in a thread."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock events
        thread_root = MagicMock(spec=RoomMessageText)
        thread_root.sender = "@user:matrix.org"
        thread_root.body = "Thread root"
        thread_root.server_timestamp = 1704110400000
        thread_root.event_id = "$thread1"
        thread_root.source = {
            "content": {
                "body": "Thread root",
                "msgtype": "m.text",
            }
        }

        thread_reply = MagicMock(spec=RoomMessageText)
        thread_reply.sender = "@user:matrix.org"
        thread_reply.body = "Thread reply"
        thread_reply.server_timestamp = 1704110500000
        thread_reply.event_id = "$reply1"
        thread_reply.source = {
            "content": {
                "body": "Thread reply",
                "msgtype": "m.text",
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$thread1",
                },
            }
        }

        other_msg = MagicMock(spec=RoomMessageText)
        other_msg.sender = "@user:matrix.org"
        other_msg.body = "Other message"
        other_msg.server_timestamp = 1704110600000
        other_msg.event_id = "$other"
        other_msg.source = {"content": {"body": "Other message", "msgtype": "m.text"}}

        # Mock the room_messages response
        mock_response = MagicMock()
        mock_response.chunk = [thread_root, thread_reply, other_msg]

        client.room_messages = AsyncMock(return_value=mock_response)

        thread_messages = await _get_thread_messages(client, "!room:matrix.org", "$thread1")
        assert len(thread_messages) == 2
        assert thread_messages[0].event_id == "$thread1"
        assert thread_messages[1].event_id == "$reply1"

    @pytest.mark.asyncio
    async def test_get_message_by_handle(self):
        """Test getting message by handle."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock events
        msg1 = MagicMock(spec=RoomMessageText)
        msg1.sender = "@user:matrix.org"
        msg1.body = "Message 1"
        msg1.server_timestamp = 1704110400000
        msg1.event_id = "$event1"
        msg1.source = {"content": {"body": "Message 1", "msgtype": "m.text"}}

        msg2 = MagicMock(spec=RoomMessageText)
        msg2.sender = "@user:matrix.org"
        msg2.body = "Message 2"
        msg2.server_timestamp = 1704110500000
        msg2.event_id = "$event2"
        msg2.source = {"content": {"body": "Message 2", "msgtype": "m.text"}}

        # Mock the room_messages response
        # Note: _get_messages reverses the order, so msg2 then msg1 in the response
        # will become msg1 then msg2 after reversal
        mock_response = MagicMock()
        mock_response.chunk = [
            msg2,
            msg1,
        ]  # Reversed order because _get_messages reverses

        client.room_messages = AsyncMock(return_value=mock_response)

        # Test with m2 format
        msg = await _get_message_by_handle(client, "!room:matrix.org", "m2")
        assert msg is not None
        assert msg.content == "Message 2"
        assert msg.handle == "m2"

        # Test with m1 format
        msg = await _get_message_by_handle(client, "!room:matrix.org", "m1")
        assert msg is not None
        assert msg.content == "Message 1"
        assert msg.handle == "m1"

        # Test not found (non-existent handle)
        msg = await _get_message_by_handle(client, "!room:matrix.org", "m999")
        assert msg is None
