"""Fixed tests for matty module to increase code coverage."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import (
    AsyncClient,
    ErrorResponse,
    LoginResponse,
    MatrixRoom,
    RoomSendResponse,
)
from typer.testing import CliRunner

from matty import (
    Config,
    Message,
    OutputFormat,
    Room,
    _create_client,
    _display_messages_json,
    _display_messages_rich,
    _display_messages_simple,
    _display_rooms_json,
    _display_rooms_rich,
    _display_rooms_simple,
    _display_users_json,
    _display_users_rich,
    _display_users_simple,
    _execute_messages_command,
    _execute_rooms_command,
    _execute_send_command,
    _execute_users_command,
    _find_room,
    _get_message_by_handle,
    _get_messages,
    _get_rooms,
    _get_thread_messages,
    _get_threads,
    _load_config,
    _login,
    _send_message,
    _sync_client,
    app,
)

runner = CliRunner()


class TestDataclasses:
    """Test dataclass functionality."""

    def test_room_dataclass(self):
        """Test Room dataclass."""
        room = Room(
            room_id="!test:matrix.org",
            name="Test Room",
            member_count=10,
            topic="Test topic",
        )
        assert room.room_id == "!test:matrix.org"
        assert room.name == "Test Room"
        assert room.member_count == 10
        assert room.topic == "Test topic"

    def test_room_dataclass_defaults(self):
        """Test Room dataclass with defaults."""
        room = Room(room_id="!test:matrix.org", name="Test", member_count=0)
        assert room.member_count == 0
        assert room.topic is None

    def test_message_with_thread(self):
        """Test Message dataclass with thread information."""
        msg = Message(
            sender="@user:matrix.org",
            content="Thread message",
            timestamp=datetime.now(UTC),
            room_id="!room:matrix.org",
            event_id="$event123",
            thread_root_id="$thread123",
            reply_to_id="$reply123",
        )
        assert msg.thread_root_id == "$thread123"
        assert msg.reply_to_id == "$reply123"
        assert msg.is_thread_root is False

    def test_config_from_env(self):
        """Test Config loading from environment variables."""
        with patch.dict(
            "os.environ",
            {
                "MATRIX_HOMESERVER": "https://custom.server",
                "MATRIX_USERNAME": "testuser",
                "MATRIX_PASSWORD": "testpass",
                "MATRIX_SSL_VERIFY": "false",
            },
        ):
            config = _load_config()
            assert config.homeserver == "https://custom.server"
            assert config.username == "testuser"
            assert config.password == "testpass"
            assert config.ssl_verify is False


class TestDisplayFunctions:
    """Test display functions."""

    def test_display_rooms_rich(self, capsys):
        """Test rich display of rooms."""
        rooms = [
            Room("!room1:matrix.org", "Room 1", 5, "Topic 1"),
            Room("!room2:matrix.org", "Room 2", 10, None),
        ]
        _display_rooms_rich(rooms)
        captured = capsys.readouterr()
        assert "Room 1" in captured.out
        # Note: Topic is not displayed in the rich table output

    def test_display_rooms_simple(self, capsys):
        """Test simple display of rooms."""
        rooms = [
            Room("!room1:matrix.org", "Room 1", 5, "Topic 1"),
            Room("!room2:matrix.org", "Room 2", 10, None),
        ]
        _display_rooms_simple(rooms)
        captured = capsys.readouterr()
        assert "Room 1" in captured.out
        assert "5 members" in captured.out

    def test_display_rooms_json(self, capsys):
        """Test JSON display of rooms."""
        rooms = [Room("!room1:matrix.org", "Room 1", 5, "Topic 1")]
        _display_rooms_json(rooms)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data[0]["name"] == "Room 1"
        assert data[0]["room_id"] == "!room1:matrix.org"

    def test_display_messages_rich(self, capsys):
        """Test rich display of messages."""
        messages = [
            Message(
                sender="@user:matrix.org",
                content="Test message",
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$event123",
            )
        ]
        _display_messages_rich(messages, "Test Room")
        captured = capsys.readouterr()
        assert "Test Room" in captured.out

    def test_display_messages_simple(self, capsys):
        """Test simple display of messages."""
        messages = [
            Message(
                sender="@user:matrix.org",
                content="Test message",
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$event123",
            )
        ]
        _display_messages_simple(messages, "Test Room")
        captured = capsys.readouterr()
        assert "Test message" in captured.out
        assert "@user:matrix.org" in captured.out

    def test_display_messages_json(self, capsys):
        """Test JSON display of messages."""
        messages = [
            Message(
                sender="@user:matrix.org",
                content="Test message",
                timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$event123",
            )
        ]
        _display_messages_json(messages, "Test Room")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["room"] == "Test Room"
        assert data["messages"][0]["content"] == "Test message"

    def test_display_users_rich(self, capsys):
        """Test rich display of users."""
        users = ["@user1:matrix.org", "@user2:matrix.org"]
        _display_users_rich(users, "Test Room")
        captured = capsys.readouterr()
        assert "Test Room" in captured.out

    def test_display_users_simple(self, capsys):
        """Test simple display of users."""
        users = ["@user1:matrix.org", "@user2:matrix.org"]
        _display_users_simple(users, "Test Room")
        captured = capsys.readouterr()
        assert "@user1:matrix.org" in captured.out
        assert "@user2:matrix.org" in captured.out

    def test_display_users_json(self, capsys):
        """Test JSON display of users."""
        users = ["@user1:matrix.org", "@user2:matrix.org"]
        _display_users_json(users, "Test Room")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["room"] == "Test Room"
        assert "@user1:matrix.org" in data["users"]


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
    async def test_send_message_reply(self):
        """Test sending a reply message."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse("$new_event123", "!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)
        # Add rooms attribute for mention parsing
        client.rooms = {
            "!room:matrix.org": MagicMock(
                users={"@user1:matrix.org": {}, "@user2:matrix.org": {}}
            )
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
        assert (
            '<a href="https://matrix.to/#/@alice:matrix.org">'
            in content["formatted_body"]
        )
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
        regular_event.source = {
            "content": {"body": "Regular message", "msgtype": "m.text"}
        }

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

        thread_messages = await _get_thread_messages(
            client, "!room:matrix.org", "$thread1"
        )
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


class TestCLICommands:
    """Test CLI commands with mocking."""

    @pytest.mark.asyncio
    async def test_execute_rooms_command(self, capsys):
        """Test execute rooms command."""
        mock_client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room:matrix.org"
        room.display_name = "Test Room"
        room.member_count = 5
        room.users = {f"@user{i}:matrix.org": None for i in range(5)}
        room.topic = "Test Topic"

        mock_client.rooms = {"!room:matrix.org": room}

        with (
            patch("matty._create_client", return_value=mock_client),
            patch("matty._login", return_value=True),
            patch("matty._sync_client", return_value=None),
            patch(
                "matty._load_config",
                return_value=Config("https://matrix.org", "user", "pass"),
            ),
        ):
            await _execute_rooms_command(
                username="user", password="pass", format=OutputFormat.simple
            )

        captured = capsys.readouterr()
        assert "Test Room" in captured.out

    @pytest.mark.asyncio
    async def test_execute_messages_command(self, capsys):
        """Test execute messages command."""
        from nio import RoomMessageText

        mock_client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room:matrix.org"
        room.display_name = "Test Room"
        room.users = {"@user1:matrix.org": None}
        room.topic = None

        mock_client.rooms = {"!room:matrix.org": room}

        # Mock message response with RoomMessageText event
        mock_event = MagicMock(spec=RoomMessageText)
        mock_event.sender = "@user:matrix.org"
        mock_event.body = "Test message"
        mock_event.server_timestamp = 1704110400000
        mock_event.event_id = "$event123"
        mock_event.source = {"content": {"body": "Test message", "msgtype": "m.text"}}

        mock_response = MagicMock()
        mock_response.chunk = [mock_event]

        mock_client.room_messages = AsyncMock(return_value=mock_response)

        with (
            patch("matty._create_client", return_value=mock_client),
            patch("matty._login", return_value=True),
            patch("matty._sync_client", return_value=None),
            patch(
                "matty._load_config",
                return_value=Config("https://matrix.org", "user", "pass"),
            ),
        ):
            await _execute_messages_command(
                room="Test Room",
                limit=10,
                username="user",
                password="pass",
                format=OutputFormat.simple,
            )

        captured = capsys.readouterr()
        assert "Test message" in captured.out

    @pytest.mark.asyncio
    async def test_execute_send_command(self, capsys):
        """Test execute send command."""
        mock_client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room:matrix.org"
        room.display_name = "Test Room"
        room.users = {"@user1:matrix.org": None}
        room.topic = None

        mock_client.rooms = {"!room:matrix.org": room}

        response = RoomSendResponse("$new_event123", "!room:matrix.org")
        mock_client.room_send = AsyncMock(return_value=response)

        with (
            patch("matty._create_client", return_value=mock_client),
            patch("matty._login", return_value=True),
            patch("matty._sync_client", return_value=None),
            patch(
                "matty._load_config",
                return_value=Config("https://matrix.org", "user", "pass"),
            ),
        ):
            await _execute_send_command(
                room="Test Room",
                message="Hello, world!",
                username="user",
                password="pass",
            )

        captured = capsys.readouterr()
        assert "sent to Test Room" in captured.out

    @pytest.mark.asyncio
    async def test_execute_users_command(self, capsys):
        """Test execute users command."""
        mock_client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room:matrix.org"
        room.display_name = "Test Room"
        room.users = {"@user1:matrix.org": None, "@user2:matrix.org": None}
        room.topic = None

        mock_client.rooms = {"!room:matrix.org": room}

        with (
            patch("matty._create_client", return_value=mock_client),
            patch("matty._login", return_value=True),
            patch("matty._sync_client", return_value=None),
            patch(
                "matty._load_config",
                return_value=Config("https://matrix.org", "user", "pass"),
            ),
        ):
            await _execute_users_command(
                room="Test Room",
                username="user",
                password="pass",
                format=OutputFormat.simple,
            )

        captured = capsys.readouterr()
        assert "@user1:matrix.org" in captured.out
        assert "@user2:matrix.org" in captured.out

    def test_cli_rooms_command(self):
        """Test CLI rooms command."""
        with patch("matty._load_config") as mock_load:
            mock_load.return_value = Config("https://matrix.org", "user", "pass")
            with patch("matty._execute_rooms_command") as mock_exec:
                mock_exec.return_value = None
                with patch("asyncio.run"):
                    result = runner.invoke(app, ["rooms"])
                    assert result.exit_code == 0

    def test_cli_messages_command(self):
        """Test CLI messages command."""
        with patch("matty._load_config") as mock_load:
            mock_load.return_value = Config("https://matrix.org", "user", "pass")
            with patch("matty._execute_messages_command") as mock_exec:
                mock_exec.return_value = None
                with patch("asyncio.run"):
                    result = runner.invoke(app, ["messages", "Test Room"])
                    assert result.exit_code == 0

    def test_cli_send_command(self):
        """Test CLI send command."""
        with patch("matty._load_config") as mock_load:
            mock_load.return_value = Config("https://matrix.org", "user", "pass")
            with patch("matty._execute_send_command") as mock_exec:
                mock_exec.return_value = None
                with patch("asyncio.run"):
                    result = runner.invoke(app, ["send", "Test Room", "Hello"])
                    assert result.exit_code == 0

    def test_cli_users_command(self):
        """Test CLI users command."""
        with patch("matty._load_config") as mock_load:
            mock_load.return_value = Config("https://matrix.org", "user", "pass")
            with patch("matty._execute_users_command") as mock_exec:
                mock_exec.return_value = None
                with patch("asyncio.run"):
                    result = runner.invoke(app, ["users", "Test Room"])
                    assert result.exit_code == 0


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_login_with_error_response(self):
        """Test login with error response."""
        client = MagicMock(spec=AsyncClient)
        error = ErrorResponse("Invalid credentials", "M_FORBIDDEN")
        client.login = AsyncMock(return_value=error)

        result = await _login(client, "wrong_pass")
        assert result is False

    @pytest.mark.asyncio
    async def test_find_room_exact_match(self):
        """Test exact room name matching (case-insensitive)."""
        client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room:matrix.org"
        room.display_name = "Test Room"
        room.users = {"@user1:matrix.org": None}
        room.topic = None

        client.rooms = {"!room:matrix.org": room}

        # Test exact match (case insensitive)
        result = await _find_room(client, "test room")
        assert result == ("!room:matrix.org", "Test Room")

        # Test partial match should NOT work
        result = await _find_room(client, "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_messages_empty_room(self):
        """Test getting messages from empty room."""
        client = MagicMock(spec=AsyncClient)

        mock_response = MagicMock()
        mock_response.chunk = []

        client.room_messages = AsyncMock(return_value=mock_response)

        messages = await _get_messages(client, "!room:matrix.org", limit=10)
        assert messages == []
