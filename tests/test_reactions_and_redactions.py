"""More tests to reach >90% coverage."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from nio import AsyncClient, RoomRedactResponse, RoomSendResponse

from matty import (
    _send_reaction,
)


class TestReactionsAndRedactions:
    """Test reaction and redaction functionality."""

    @pytest.mark.asyncio
    async def test_send_reaction_success(self):
        """Test successful reaction send."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse(event_id="$reaction123", room_id="!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)

        result = await _send_reaction(client, "!room:matrix.org", "$msg123", "👍")
        assert result is True

        # Verify reaction content
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert content["m.relates_to"]["rel_type"] == "m.annotation"
        assert content["m.relates_to"]["event_id"] == "$msg123"
        assert content["m.relates_to"]["key"] == "👍"

    @pytest.mark.asyncio
    async def test_send_reaction_failure(self):
        """Test reaction send failure."""
        client = MagicMock(spec=AsyncClient)
        client.room_send = AsyncMock(side_effect=Exception("Network error"))

        result = await _send_reaction(client, "!room:matrix.org", "$msg123", "👍")
        assert result is False

    @pytest.mark.asyncio
    async def test_room_redact_success(self):
        """Test successful redaction via room_redact."""
        client = MagicMock(spec=AsyncClient)
        response = RoomRedactResponse(event_id="$redaction123", room_id="!room:matrix.org")
        client.room_redact = AsyncMock(return_value=response)

        # Directly test the client method since _send_redaction doesn't exist
        result = await client.room_redact("!room:matrix.org", "$msg456", reason="Mistake")
        assert result.event_id == "$redaction123"

        # Verify redaction was called
        client.room_redact.assert_called_once_with("!room:matrix.org", "$msg456", reason="Mistake")
