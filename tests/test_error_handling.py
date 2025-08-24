"""Additional tests to improve coverage to >90%."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from nio import AsyncClient, ErrorResponse, MatrixRoom
from typer.testing import CliRunner

from matty import (
    _find_room,
    _get_messages,
    _login,
    _send_message,
    _sync_client,
)

runner = CliRunner()


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
    async def test_send_message_exception(self):
        """Test send message with exception."""
        client = MagicMock(spec=AsyncClient)
        client.room_send = AsyncMock(side_effect=Exception("Network error"))

        result = await _send_message(client, "!room:matrix.org", "Test")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_messages_error_response(self):
        """Test get messages with error response."""
        client = MagicMock(spec=AsyncClient)
        error = ErrorResponse("Forbidden", "M_FORBIDDEN")
        client.room_messages = AsyncMock(return_value=error)

        messages = await _get_messages(client, "!room:matrix.org", 10)
        assert messages == []

    @pytest.mark.asyncio
    async def test_sync_client_error(self):
        """Test sync client with error."""
        client = MagicMock(spec=AsyncClient)
        error = ErrorResponse("Sync failed", "M_UNKNOWN")
        client.sync = AsyncMock(return_value=error)

        # Should handle error gracefully
        await _sync_client(client)

    @pytest.mark.asyncio
    async def test_find_room_partial_match(self):
        """Test finding room with partial name match doesn't work."""
        client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room:matrix.org"
        room.display_name = "Test Room"
        room.users = {"@user1:matrix.org": None}
        room.topic = None
        room.member_count = 1

        client.rooms = {"!room:matrix.org": room}

        # Partial match should not work
        result = await _find_room(client, "Test")
        assert result is None

        # Exact match (case insensitive) should work
        result = await _find_room(client, "test room")
        assert result == ("!room:matrix.org", "Test Room")

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
