"""Additional tests to improve coverage to >90%."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import AsyncClient, MatrixRoom
from typer.testing import CliRunner

from matty import (
    OutputFormat,
    _execute_messages_command,
    _execute_rooms_command,
    _execute_send_command,
    _execute_users_command,
)

runner = CliRunner()


class TestAsyncCommandExecution:
    """Test async command execution functions."""

    @pytest.mark.asyncio
    async def test_execute_rooms_command_success(self, capsys):
        """Test successful rooms command execution."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=True):
                room = MagicMock(spec=MatrixRoom)
                room.room_id = "!room:matrix.org"
                room.display_name = "Test Room"
                room.member_count = 5
                room.topic = "Test Topic"
                room.users = {f"@user{i}:matrix.org": None for i in range(5)}

                client.rooms = {"!room:matrix.org": room}
                client.close = AsyncMock()

                await _execute_rooms_command("user", "pass", OutputFormat.simple)

        captured = capsys.readouterr()
        assert "Test Room" in captured.out

    @pytest.mark.asyncio
    async def test_execute_rooms_command_login_fail(self, capsys):
        """Test rooms command with login failure."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=False):
                client.close = AsyncMock()

                await _execute_rooms_command("user", "pass", OutputFormat.simple)

        captured = capsys.readouterr()
        assert captured.out == ""

    @pytest.mark.asyncio
    async def test_execute_messages_command_room_not_found(self, capsys):
        """Test messages command when room not found."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with (
                patch("matty._login", return_value=True),
                patch("matty._sync_client", return_value=None),
                patch("matty._find_room", return_value=None),
            ):
                client.close = AsyncMock()

                await _execute_messages_command(
                    "NonExistent", 10, "user", "pass", OutputFormat.simple
                )

        captured = capsys.readouterr()
        assert "not found" in captured.out.lower()

    @pytest.mark.asyncio
    async def test_execute_send_command_with_mentions(self):
        """Test send command with mentions."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with (
                patch("matty._login", return_value=True),
                patch("matty._sync_client", return_value=None),
                patch("matty._find_room", return_value=("!room:matrix.org", "Test Room")),
                patch("matty._send_message", return_value=True) as mock_send,
            ):
                client.close = AsyncMock()

                await _execute_send_command("Test Room", "@alice hello", "user", "pass")

                # Verify _send_message was called
                mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_users_command_json(self, capsys):
        """Test users command with JSON output."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with (
                patch("matty._login", return_value=True),
                patch("matty._sync_client", return_value=None),
            ):
                room = MagicMock(spec=MatrixRoom)
                room.room_id = "!room:matrix.org"
                room.display_name = "Test Room"
                room.topic = "Test topic"
                room.member_count = 2
                room.users = {"@alice:matrix.org": None, "@bob:matrix.org": None}

                client.rooms = {"!room:matrix.org": room}

                with patch("matty._find_room", return_value=("!room:matrix.org", "Test Room")):
                    client.close = AsyncMock()

                    await _execute_users_command("Test Room", "user", "pass", OutputFormat.json)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["room"] == "Test Room"
        assert len(data["users"]) == 2
