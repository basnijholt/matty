"""Additional tests to improve coverage to >90%."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import (
    AsyncClient,
    MatrixRoom,
    RoomSendResponse,
)
from typer.testing import CliRunner

from matty import (
    Config,
    OutputFormat,
    _execute_messages_command,
    _execute_rooms_command,
    _execute_send_command,
    _execute_users_command,
    app,
)

runner = CliRunner()


class TestCLICommands:
    """Test CLI command execution."""

    def test_cli_help(self):
        """Test help command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Functional Matrix CLI client" in result.output

    def test_cli_rooms_no_creds(self):
        """Test rooms command without credentials."""
        with patch("matty._load_config") as mock_load:
            mock_load.return_value = Config("https://matrix.org", None, None)
            # Mock the async execution to avoid actual connection
            with patch("matty.asyncio.run") as mock_run:
                mock_run.side_effect = Exception("No credentials")
                result = runner.invoke(app, ["rooms"])
                # Should handle the exception
                assert result.exit_code == 1

    def test_cli_messages_no_room(self):
        """Test messages command without room argument."""
        result = runner.invoke(app, ["messages"])
        assert result.exit_code != 0

    def test_cli_send_no_message(self):
        """Test send command without message."""
        result = runner.invoke(app, ["send", "TestRoom"])
        assert result.exit_code != 0

    def test_cli_thread_start_no_handle(self):
        """Test thread-start command without handle."""
        result = runner.invoke(app, ["thread-start", "TestRoom"])
        assert result.exit_code != 0

    def test_cli_react_no_emoji(self):
        """Test react command without emoji."""
        result = runner.invoke(app, ["react", "TestRoom", "m1"])
        assert result.exit_code != 0

    def test_cli_edit_no_content(self):
        """Test edit command without new content."""
        result = runner.invoke(app, ["edit", "TestRoom", "m1"])
        assert result.exit_code != 0

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
